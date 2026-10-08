#!/usr/bin/env python3
"""Two agents through two proxies against the fake Vivado MCP server. --verifier stub|fam."""
import argparse, json, subprocess, sys, time, os
ap = argparse.ArgumentParser(); ap.add_argument("--verifier", default="stub"); ap.add_argument("--fam-endpoint", default="192.168.1.88:5055")
ap.add_argument("--repeat", type=int, default=1); a = ap.parse_args()
here = os.path.dirname(os.path.abspath(__file__)); state = os.path.join(here, "test_versions.json")
def start(agent):
    return subprocess.Popen([sys.executable, "-m", "pranaxis_gateway", "--agent-id", agent, "--verifier", a.verifier, "--fam-endpoint", a.fam_endpoint,
                             "--state-file", state, "--log-file", os.path.join(here, "test_log.jsonl"), "--", sys.executable, os.path.join(here, "fake_vivado_mcp.py")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
n = [0]
def call(p, method, params=None):
    n[0] += 1; p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": n[0], "method": method, "params": params or {}}) + "\n"); p.stdin.flush()
    return json.loads(p.stdout.readline())
ok_all = True
for rep in range(1, a.repeat + 1):
    if os.path.exists(state): os.remove(state)
    sess = f"s{rep}"
    A = start("agent-a"); B = start("agent-b"); call(A, "initialize", {}); call(B, "initialize", {})
    ex = lambda p, cmd: call(p, "tools/call", {"name": "vivado_execute", "arguments": {"session_id": sess, "command": cmd}})
    st = lambda p, act, **kw: call(p, "tools/call", {"name": "vivado_status", "arguments": dict(session_id=sess, action=act, **kw)})
    res = {}
    res["P1"] = not ex(A, "launch_runs impl_1 -jobs 8")["result"].get("isError")
    res["P2"] = bool(ex(B, "launch_runs impl_1 -jobs 8")["result"].get("isError"))
    t0 = time.time(); r = st(B, "runs"); res["P3"] = (not r["result"].get("isError")) and (time.time() - t0) < 0.05
    ex(A, "wait_on_run impl_1"); time.sleep(0.2)
    res["P4a"] = bool(ex(B, "launch_runs impl_1 -jobs 8")["result"].get("isError"))   # 0.2: holder has not collected its result yet -> still denied
    ex(A, "get_property STATS.WNS [get_runs impl_1]")                                   # holder collects -> version advances
    res["P4"] = not ex(B, "launch_runs impl_1 -jobs 8")["result"].get("isError")
    A.stdin.close(); B.stdin.close()
    ok = all(res.values()); ok_all &= ok
    print(f"pasada {rep}: " + "  ".join(f"{k}={'ok' if v else 'FALLA'}" for k, v in res.items()) + ("" if ok else "   <-- revisar"))
print("RESULTADO:", "todas las predicciones sostenidas" if ok_all else "alguna predicción falla; no enseñar la demo")
