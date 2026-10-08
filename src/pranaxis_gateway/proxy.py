#!/usr/bin/env python3
"""Pranaxis MCP Gateway: consistency verdicts for MCP tool calls (stdio proxy).

Sits between an MCP client (Claude Code, Cursor, Codex...) and the AMD Ross Vivado MCP server.
Every JSON-RPC message is forwarded unchanged, except `tools/call` requests that would MODIFY the
shared Vivado project. Those are turned into a consistency event (agent, resource, version) and sent
to the Pranaxis verifier before being forwarded; a DENY verdict is returned to the client as an MCP
tool error carrying the certificate, and the call never reaches Vivado.

    client  --stdio-->  pranaxis_mcp.py  --stdio-->  vivado-mcp-server --stdio-bridge  --Tcl-->  Vivado
                                 |
                                 +--HTTP /verdict-->  fam_server.py on the ZUBoard (or software stub)

Consumption rules are declarative (0.3): --rules <file.json>, one file per MCP server (see rules/ and
pranaxis_rules.py). Default: rules/vivado-ross.json, which reproduces the 0.2 behaviour for AMD Ross.
A call that matches no rule passes without measurement and is logged as passthrough.

Versions: kept per (session, resource) in a small JSON state file shared by all proxies on the machine.
When a run completes (wait_on_run returned, or vivado_status reporting it Complete) it stays with its holder,
'pending release', until the holder makes its next call (it has collected the result) or the grace period
(--grace, default 600 s) expires; only then does the version advance. The chip keeps the holders.

Usage (register in Claude Code, one proxy per agent):
  claude mcp add vivado-mcp --scope user --transport stdio --env VIVADO_PATH=... -- \
      python pranaxis_mcp.py --agent-id agent-a --verifier fam --fam-endpoint 192.168.1.88:5055 \
      -- C:\\tools\\vivado-mcp-server-windows-amd64-2026.9.1.exe --stdio-bridge
"""
import argparse, datetime, hashlib, json, os, re, subprocess, sys, threading, time, urllib.request, uuid
from .rules import RuleSet

IMPL = "pranaxis-mcp-gateway"; VERSION = "0.3.0"
_LEGACY_WRITE_CMDS = ("launch_runs", "reset_runs", "reset_run", "synth_design", "opt_design", "place_design", "route_design",
              "phys_opt_design", "write_bitstream", "write_device_image", "write_checkpoint", "save_constraints",
              "close_project", "create_project", "add_files", "remove_files", "set_property")
RUN_CMDS = ("launch_runs", "reset_runs", "reset_run", "wait_on_run")
DESIGN_CMDS = ("synth_design", "opt_design", "place_design", "route_design", "phys_opt_design", "write_bitstream",
               "write_device_image", "write_checkpoint", "save_constraints")
NOTE = ("\n\nNOTE (Pranaxis consistency verifier): write operations (launch_runs, reset_runs, synth/place/route, "
        "write_bitstream, write_checkpoint, set_property...) are arbitrated by an external physical verifier. "
        "A denied call returns isError=true with the holder and a certificate id; the resource version is being "
        "consumed by another agent. Do not retry the same write blindly: check vivado_status(action='runs') and wait, "
        "or do read-only work until the holder's run completes.")

def log(msg): sys.stderr.write(f"[{IMPL}] {msg}\n"); sys.stderr.flush()

# ---------------------------------------------------------------- state (versions), shared on disk
class State:
    """versions per resource, shared on disk. A completed run does not advance its version at once: it is marked
    'pending release' by its holder; the version advances when the holder makes its next call (collects the result)
    or when the grace period expires. Meanwhile other agents' writes still hit the chip on the old version -> DENY."""
    def __init__(self, path, grace_s): self.path = path; self.grace_s = grace_s; self.lock = threading.Lock()
    def _load(self):
        try: return json.load(open(self.path))
        except Exception: return {}
    def _save(self, d): json.dump(d, open(self.path, "w"))
    def _expire(self, d):
        now = time.time(); pend = d.setdefault("pending", {})
        for key in list(pend):
            if now - pend[key]["since"] >= self.grace_s:
                v = d.setdefault("versions", {}); v[key] = int(v.get(key, 1)) + 1; pend.pop(key)
    def version(self, key):
        with self.lock:
            d = self._load(); self._expire(d); self._save(d); return int(d.get("versions", {}).get(key, 1))
    def pending(self, key):
        with self.lock:
            d = self._load(); self._expire(d); self._save(d); return d.get("pending", {}).get(key)
    def mark_pending(self, key, holder):
        with self.lock:
            d = self._load(); d.setdefault("pending", {})[key] = {"holder": holder, "since": time.time()}; self._save(d)
    def release_by(self, holder):
        """holder made a call after completion -> its pending resources advance; returns the keys advanced"""
        with self.lock:
            d = self._load(); pend = d.setdefault("pending", {}); out = []
            for key in list(pend):
                if pend[key]["holder"] == holder:
                    v = d.setdefault("versions", {}); v[key] = int(v.get(key, 1)) + 1; pend.pop(key); out.append((key, v[key]))
            self._save(d); return out

# ---------------------------------------------------------------- verifiers
class StubVerifier:
    """software reference; holders shared with the other proxies through the state file (the chip does this itself)"""
    name = "stub"
    def __init__(self, state): self.state = state
    def verdict(self, ev):
        key = f"{ev['resource']}@{ev['version']}"
        with self.state.lock:
            d = self.state._load(); holders = d.setdefault("holders", {}); prev = holders.get(key)
            if prev is None:
                holders[key] = [ev["sandbox_id"], ev["request_id"]]; ok, reason, conf = True, "first consumer of this resource version", ""
            elif prev[0] == ev["sandbox_id"]: ok, reason, conf = True, "same agent re-sending its own consumption", prev[1]
            else: ok, reason, conf = False, "resource version already consumed by another agent", prev[1]
            json.dump(d, open(self.state.path, "w"))
        cert = "stub-" + hashlib.sha256(json.dumps([key, ev["sandbox_id"], ev["request_id"]]).encode()).hexdigest()[:16]
        return dict(consistent=ok, reason=reason, certificate_id=cert, conflicting_with=conf, criba=[], f_MHz=[],
                    tolerance="none (software stub)", medido=False, holder=holders.get(key, [""])[0])

class FamVerifier:
    name = "fam"
    def __init__(self, endpoint, timeout_s): self.endpoint = endpoint; self.timeout_s = timeout_s
    def verdict(self, ev):
        body = json.dumps(dict(sandbox_id=ev["sandbox_id"], request_id=ev["request_id"], resource=ev["resource"], version=ev["version"])).encode()
        req = urllib.request.Request(f"http://{self.endpoint}/verdict", data=body, headers={"content-type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout_s) as r: return json.loads(r.read())

def resolve_rules(name_or_path):
    if os.path.exists(name_or_path): return name_or_path
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules", f"{name_or_path}.json")
    if os.path.exists(p): return p
    raise SystemExit(f"rules not found: {name_or_path} (bundled: vivado-ross, github-official, postgres-generic)")

# ---------------------------------------------------------------- proxy
class Proxy:
    def __init__(self, a):
        self.a = a; self.state = State(a.state_file, a.grace); self.rules = RuleSet(resolve_rules(a.rules))
        self.write_tools = {r.get("tool", "*") for r in self.rules.consume}
        self.verifier = FamVerifier(a.fam_endpoint, a.verifier_timeout) if a.verifier == "fam" else StubVerifier(self.state)
        self.pending = {}  # id -> (tool name, args)
        self.lock = threading.Lock(); self.jsonl = open(a.log_file, "a")
        self.child = subprocess.Popen(a.child, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr, bufsize=0)
        log(f"{IMPL} {VERSION} agent={a.agent_id} verifier={self.verifier.name} child={' '.join(a.child)}")

    def record(self, **kw):
        kw["t_utc"] = datetime.datetime.utcnow().isoformat(timespec="milliseconds") + "Z"; kw["agent"] = self.a.agent_id
        self.jsonl.write(json.dumps(kw) + "\n"); self.jsonl.flush()

    def send_client(self, msg):
        with self.lock: sys.stdout.write(json.dumps(msg) + "\n"); sys.stdout.flush()
    def send_child(self, line): self.child.stdin.write(line.encode() if isinstance(line, str) else line); self.child.stdin.flush()

    def deny_response(self, rid, ev, v):
        text = (f"DENIED by the Pranaxis consistency verifier.\n"
                f"Resource '{ev['resource']}' version {ev['version']} is being consumed by another agent "
                f"(holder: {v.get('holder') or 'unknown'}; their request: {v.get('conflicting_with') or '?'}).\n"
                f"Reason: {v.get('reason')}\nCertificate: {v.get('certificate_id')}  tolerance: {v.get('tolerance')}  "
                f"sieve: {v.get('criba')}  measured: {v.get('medido')}\n"
                f"Your call did NOT reach Vivado. Do not retry the same write; check vivado_status(action='runs'), "
                f"wait for the holder's run to complete, or do read-only work.")
        return {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": text}], "isError": True}}

    def on_client_line(self, line):
        try: msg = json.loads(line)
        except Exception: self.send_child(line); return
        if msg.get("method") == "tools/call":
            p = msg.get("params", {}) or {}; name = p.get("name"); args = p.get("arguments") or {}
            for key, nv in self.state.release_by(self.a.agent_id):
                self.record(kind="version_bump", resource=key, version=nv, by="holder_release"); log(f"{key} released by holder -> version {nv}")
            cons = self.rules.consumes(name, args)
            if "id" in msg: self.pending[msg["id"]] = (name, args)
            if cons:
                for key, explicit_ver, rule in cons:
                    ver = explicit_ver if explicit_ver is not None else self.state.version(key)
                    ev = dict(sandbox_id=self.a.agent_id, request_id=f"{self.a.agent_id}-{uuid.uuid4().hex[:8]}", resource=key, version=ver)
                    t0 = time.time()
                    try: v = self.verifier.verdict(ev)
                    except Exception as e:
                        v = dict(consistent=False, reason=f"verifier unreachable: {e}", certificate_id="", conflicting_with="", holder="", tolerance="", criba=[], medido=False)
                    dt = round((time.time() - t0) * 1000)
                    self.record(kind="verdict", tool=name, resource=key, version=ver, request_id=ev["request_id"], verdict=v, proxy_ms=dt, args=args)
                    log(f"{name} {key} v{ver} -> {'ALLOW' if v.get('consistent') else 'DENY'} ({v.get('reason')}) {dt} ms {v.get('certificate_id')}")
                    if not v.get("consistent"):
                        pend = self.state.pending(key)
                        if pend: v["reason"] = f"{v.get('reason')}; the holder's run has completed but the holder has not collected its result yet (grace {self.a.grace:.0f}s)"
                        self.pending.pop(msg.get("id"), None); self.send_client(self.deny_response(msg.get("id"), ev, v)); return
            else:
                self.record(kind="passthrough", tool=name, args={k: args[k] for k in args if k != "command"} | ({"command": args.get("command")} if "command" in args else {}))
        self.send_child(line)

    def on_child_line(self, line):
        try: msg = json.loads(line)
        except Exception: sys.stdout.write(line if isinstance(line, str) else line.decode()); sys.stdout.flush(); return
        rid = msg.get("id")
        if rid in self.pending and "result" in msg:
            name, args = self.pending.pop(rid)
            text = "".join(c.get("text", "") for c in (msg["result"].get("content") or []) if isinstance(c, dict))
            for key in self.rules.releases(name, args, text):
                self.state.mark_pending(key, self.a.agent_id)
                self.record(kind="pending_release", resource=key); log(f"run {key} complete -> pending release by {self.a.agent_id} (grace {self.a.grace:.0f}s)")
        if "result" in msg and isinstance(msg["result"], dict) and "tools" in msg["result"]:
            for t in msg["result"]["tools"]:
                if any(__import__("fnmatch").fnmatchcase(t.get("name") or "", w) for w in self.write_tools): t["description"] = (t.get("description") or "") + NOTE
            self.send_client(msg); return
        self.send_client(msg)

    def run(self):
        def pump_child():
            for raw in self.child.stdout:
                self.on_child_line(raw.decode(errors="replace"))
            log("child exited"); os._exit(self.child.poll() or 0)
        threading.Thread(target=pump_child, daemon=True).start()
        for raw in sys.stdin.buffer:
            line = raw.decode(errors="replace")
            if line.strip(): self.on_client_line(line)
        try: self.child.stdin.close()
        except Exception: pass
        self.child.wait(timeout=10)

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent-id", required=True)
    ap.add_argument("--verifier", choices=["stub", "fam"], default="stub")
    ap.add_argument("--fam-endpoint", default="192.168.1.88:5055")
    ap.add_argument("--verifier-timeout", type=float, default=8.0)
    ap.add_argument("--grace", type=float, default=600.0, help="seconds a completed run stays with its holder until the holder collects the result")
    ap.add_argument("--rules", default="vivado-ross", help="rules file for the child MCP server: a bundled name (vivado-ross, github-official, postgres-generic) or a path to a JSON file")
    ap.add_argument("--state-file", default=os.path.join(os.path.expanduser("~"), ".pranaxis_mcp_versions.json"))
    ap.add_argument("--log-file", default=f"ross_demo_{datetime.date.today():%Y%m%d}.jsonl")
    ap.add_argument("child", nargs=argparse.REMAINDER, help="-- <vivado-mcp-server executable> --stdio-bridge")
    a = ap.parse_args()
    if a.child and a.child[0] == "--": a.child = a.child[1:]
    if not a.child: ap.error("child MCP server command required after --")
    Proxy(a).run()

if __name__ == "__main__": main()
