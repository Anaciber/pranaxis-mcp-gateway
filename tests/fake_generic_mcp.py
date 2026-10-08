#!/usr/bin/env python3
"""Minimal fake MCP server exposing GitHub-like and SQL-like tools, to test rule files other than Vivado."""
import json, sys
TOOLS=[{"name":n,"description":f"fake {n}","inputSchema":{"type":"object"}} for n in ("query","execute","create_or_update_file","push_files","merge_pull_request","get_file_contents")]
def out(m): sys.stdout.write(json.dumps(m)+"\n"); sys.stdout.flush()
for raw in sys.stdin:
    try: msg=json.loads(raw)
    except Exception: continue
    mid,method,p=msg.get("id"),msg.get("method"),msg.get("params") or {}
    if method=="initialize": out({"jsonrpc":"2.0","id":mid,"result":{"protocolVersion":"2025-06-18","capabilities":{"tools":{}},"serverInfo":{"name":"fake-generic","version":"0"}}})
    elif method=="tools/list": out({"jsonrpc":"2.0","id":mid,"result":{"tools":TOOLS}})
    elif method=="tools/call": out({"jsonrpc":"2.0","id":mid,"result":{"content":[{"type":"text","text":"ok "+p.get("name","")}]}})
    elif mid is not None: out({"jsonrpc":"2.0","id":mid,"result":{}})
