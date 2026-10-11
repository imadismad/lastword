"""Prove Bedrock reader -> badge -> live L1 payment with a UNIQUE quote (fresh hash)."""
import sys, time, uuid
import requests

D = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8090"
SUP = "0x1111111111111111111111111111111111111111"
# unique ref -> unique quote hash -> unique reqId (avoids C6 duplicate-quote revert)
ref = "Q-" + uuid.uuid4().hex[:10]
QUOTE = f"ACME Components SAS\nQuote ref: {ref}\nBeneficiary: {SUP}\nTotal due: 250000000 USD\nValidity: 30 days\n"

requests.put(f"{D}/api/config", json={
    "reader_mode": "bedrock", "region": "us-east-1",
    "bedrock_model": "us.anthropic.claude-sonnet-4-20250514-v1:0",
    "whitelist": {"ACME Components SAS": {"beneficiary": SUP, "cap": 1_000_000_000, "active": True}},
    "policy": {"allowed_currencies": ["USD", "USDC", "dUSD"]},
}, timeout=10)

print("evaluate via Bedrock, ref =", ref)
res = requests.post(f"{D}/api/evaluate_text", json={"text": QUOTE}, timeout=60).json()
print("  reader =", res["reader"], "| verdict =", res["verdict"])
if res["reader"] != "bedrock" or res["verdict"] != "ASK_BADGE" or not res.get("proposal"):
    print("FAIL: expected bedrock + ASK_BADGE + proposal"); sys.exit(1)

sub = requests.post(f"{D}/api/submit", json={"proposal": res["proposal"]}, timeout=20).json()
reqId = sub["reqId"]
print("  submitted reqId =", reqId)
final = None
for _ in range(50):
    time.sleep(1.5)
    s = requests.get(f"{D}/api/status/{reqId}", timeout=10).json()
    if s["status"] in ("approved", "refused", "error", "expired"):
        final = s; break
print("  final:", final and final["status"])
if final and final["status"] == "approved":
    print("PASS: Bedrock-read invoice PAID on the live L1 via the badge. tx:")
    for k, v in (final.get("explorer_links") or {}).items():
        print("   ", k, v)
    sys.exit(0)
print("FAIL:", final); sys.exit(1)
