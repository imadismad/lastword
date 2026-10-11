"""Flip the dashboard reader to Bedrock and evaluate a quote; confirm the reader name
changes to 'bedrock' (i.e. Claude actually ran, not the local fallback)."""
import sys
import requests

D = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8090"
SUP = "0x1111111111111111111111111111111111111111"
QUOTE = f"ACME Components SAS\nQuote ref: Q-9001\nBeneficiary: {SUP}\nTotal due: 250000000 USD\n"

cfg = requests.get(f"{D}/api/config", timeout=10).json()
print("current reader_mode:", cfg["reader_mode"], "| model:", cfg.get("bedrock_model"))

model = sys.argv[2] if len(sys.argv) > 2 else "anthropic.claude-sonnet-4-20250514-v1:0"
print("switching reader -> bedrock, model =", model)
r = requests.put(f"{D}/api/config", json={
    "reader_mode": "bedrock",
    "bedrock_model": model,
    "region": "us-east-1",
    "whitelist": {"ACME Components SAS": {"beneficiary": SUP, "cap": 1_000_000_000, "active": True}},
    "policy": {"allowed_currencies": ["USD", "USDC", "dUSD"]},
}, timeout=10).json()
print("now reader_mode:", r["reader_mode"], "| model:", r.get("bedrock_model"))

print("evaluating with Bedrock ...")
res = requests.post(f"{D}/api/evaluate_text", json={"text": QUOTE}, timeout=60).json()
print("reader used:", res["reader"])
print("verdict:", res["verdict"], "| beneficiary:", res["extracted"].get("beneficiary"),
      "| amount:", res["extracted"].get("amount"))
if res["reader"] == "bedrock":
    print("RESULT: PASS — Bedrock (Claude) actually performed the extraction")
    sys.exit(0)
print("RESULT: reader fell back to", res["reader"], "(Bedrock not used)")
sys.exit(1)
