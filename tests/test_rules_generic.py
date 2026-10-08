#!/usr/bin/env python3
"""GitHub and SQL rule files against a generic fake MCP server (stub verifier)."""
import subprocess, json, sys, os
here=os.path.dirname(os.path.abspath(__file__)); state=os.path.join(here,"test_generic_versions.json")
def start(agent, rules):
    return subprocess.Popen([sys.executable,"-m","pranaxis_gateway","--agent-id",agent,"--verifier","stub","--state-file",state,"--log-file",os.path.join(here,"test_log.jsonl"),"--rules",rules.replace(".json",""),"--",sys.executable,os.path.join(here,"fake_generic_mcp.py")],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1)
n=[0]
def call(p,m,pr=None):
    n[0]+=1; p.stdin.write(json.dumps({"jsonrpc":"2.0","id":n[0],"method":m,"params":pr or {}})+"\n"); p.stdin.flush(); return json.loads(p.stdout.readline())
r=lambda x: "DENY" if x["result"].get("isError") else "ALLOW"
ok=True
if os.path.exists(state): os.remove(state)
A=start("agent-a","github-official.json"); B=start("agent-b","github-official.json"); call(A,"initialize",{}); call(B,"initialize",{})
f=lambda p,sha: call(p,"tools/call",{"name":"create_or_update_file","arguments":{"owner":"o","repo":"r","branch":"main","path":"README.md","sha":sha,"content":"x"}})
res=[r(f(A,"sha1")),r(f(B,"sha1")),r(f(B,"sha2")),r(call(B,"tools/call",{"name":"get_file_contents","arguments":{"owner":"o","repo":"r","path":"README.md"}}))]
print("GitHub:", res, "esperado ['ALLOW','DENY','ALLOW','ALLOW']"); ok&=res==["ALLOW","DENY","ALLOW","ALLOW"]
A.stdin.close(); B.stdin.close(); os.remove(state)
A=start("agent-a","postgres-generic.json"); B=start("agent-b","postgres-generic.json"); call(A,"initialize",{}); call(B,"initialize",{})
q=lambda p,sql: call(p,"tools/call",{"name":"query","arguments":{"sql":sql}})
res=[r(q(A,"UPDATE orders SET status='paid' WHERE order_id = '43'")),r(q(B,"UPDATE orders SET status='paid' WHERE order_id = '43'")),r(q(B,"UPDATE orders SET status='paid' WHERE order_id = '44'")),r(q(B,"SELECT * FROM orders"))]
print("SQL   :", res, "esperado ['ALLOW','DENY','ALLOW','ALLOW']"); ok&=res==["ALLOW","DENY","ALLOW","ALLOW"]
A.stdin.close(); B.stdin.close(); os.path.exists(state) and os.remove(state)
print("RESULTADO:", "reglas sostenidas" if ok else "alguna regla falla")
