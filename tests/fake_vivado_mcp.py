#!/usr/bin/env python3
"""Minimal fake of the AMD Ross Vivado MCP server over stdio (newline-delimited JSON-RPC)."""
import json, sys
TOOLS = [{"name": n, "description": f"fake {n}", "inputSchema": {"type": "object"}} for n in
         ("vivado_start", "vivado_stop", "vivado_connect", "vivado_list_sessions", "vivado_execute", "vivado_status", "vivado_log_messages", "vivado_history")]
runs = {"impl_1": "Not started", "synth_1": "Not started"}
def out(m): sys.stdout.write(json.dumps(m) + "\n"); sys.stdout.flush()
for raw in sys.stdin:
    try: msg = json.loads(raw)
    except Exception: continue
    mid, method, p = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if method == "initialize": out({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake-vivado-mcp", "version": "0"}}})
    elif method == "tools/list": out({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name, a = p.get("name"), p.get("arguments") or {}; txt = "ok"
        if name == "vivado_execute":
            c = a.get("command", "")
            if c.startswith("launch_runs"):
                r = c.split()[1]; runs[r] = "Running"; txt = f"launched {r}"
            elif c.startswith("wait_on_run"):
                r = c.split()[1]; runs[r] = "Complete"; txt = f"{r} Complete"
            else: txt = f"executed: {c}"
        elif name == "vivado_status":
            txt = "\n".join(f"{k}: {v}" for k, v in runs.items()) if a.get("action") == "runs" else "session healthy"
        out({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": txt}]}})
    elif mid is not None: out({"jsonrpc": "2.0", "id": mid, "result": {}})
