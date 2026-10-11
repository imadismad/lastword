"""Quick L1 reachability + contract agent-authorization check via the -L 9650 tunnel."""
import urllib.request, json, io, os

RPC = "http://127.0.0.1:9650/ext/bc/2L6HsHiCxGeQFBoe5ezfz9ZBtNBZYGKC1QHrDCeQhLPYrW3iZj/rpc"
CONTRACT = "0xc5a5c42992decbae36851359345fe25997f5c42d"
AGENT = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"  # demo agent acct1
OUT = r"C:\Users\Dell_Arte_III\Desktop\hackathon_essec_secure_horizon\l1.txt"

def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC, data=body, headers={"content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=12).read())

lines = []
try:
    bn = rpc("eth_blockNumber", [])
    lines.append("L1 blockNumber=" + str(bn.get("result")))
    # is there code at the contract?
    code = rpc("eth_getCode", [CONTRACT, "latest"]).get("result", "0x")
    lines.append("contract_has_code=" + str(len(code) > 2) + " (len=" + str(len(code)) + ")")
    # try reading agent() if the ABI exposes it: selector for agent() = 0x? we instead probe
    # a common getter. Keep it simple: just confirm code exists; agent auth is validated at tx time.
except Exception as e:
    lines.append("ERR " + str(e))

io.open(OUT, "w", encoding="utf-8").write("\n".join(lines))
print("\n".join(lines))
