"""End-to-end self-test of the dashboard HTTP API (what the browser does).

Drives: GET /api/config -> seed a supplier via PUT -> POST /api/evaluate_text (legit quote)
-> POST /api/submit -> poll /api/status until approved. Prove the browser flow pays on-chain.

Requires: anvil + badge-sim + bridge + dashboard all running, with a fresh contract whose
whitelist already has the supplier (the harness seeds 0x1111... at deploy).
"""
import sys
import time

import requests

DASH = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8090"
SUPPLIER_ADDR = "0x1111111111111111111111111111111111111111"

LEGIT_QUOTE = f"""\
ACME Components SAS
Quote ref: Q-2026-5512
Beneficiary: {SUPPLIER_ADDR}
Total due: 250000000 USD
Validity: 30 days
"""


def main():
    print("1) GET /api/config")
    cfg = requests.get(f"{DASH}/api/config", timeout=10).json()
    print("   reader_mode =", cfg["reader_mode"], "| bridge =", cfg["bridge_url"])

    # Make sure the dashboard's guard whitelist matches the on-chain supplier so C1 passes.
    print("2) PUT /api/config (whitelist ACME -> supplier addr)")
    wl = {"ACME Components SAS": {"beneficiary": SUPPLIER_ADDR, "cap": 1_000_000_000,
                                  "active": True}}
    requests.put(f"{DASH}/api/config", json={"whitelist": wl,
                 "policy": {"allowed_currencies": ["USD", "USDC", "dUSD"]}}, timeout=10)

    print("3) POST /api/evaluate_text (legit quote)")
    res = requests.post(f"{DASH}/api/evaluate_text",
                        json={"text": LEGIT_QUOTE, "deadline_mins": 10, "token": 0},
                        timeout=30).json()
    print(f"   verdict={res['verdict']} score={res['score']} reader={res['reader']}")
    print(f"   extracted beneficiary={res['extracted'].get('beneficiary')} "
          f"amount={res['extracted'].get('amount')}")
    print(f"   criteria={res['reasons']}")
    if res["verdict"] != "ASK_BADGE" or not res.get("proposal"):
        print("   FAIL: expected ASK_BADGE with a prepared proposal")
        return 1

    print("4) POST /api/submit (-> bridge -> badge -> chain)")
    sub = requests.post(f"{DASH}/api/submit", json={"proposal": res["proposal"]},
                        timeout=20).json()
    reqId = sub["reqId"]
    print(f"   reqId={reqId} status={sub['status']}")

    print("5) poll /api/status until terminal")
    final = None
    for _ in range(40):
        time.sleep(1.5)
        s = requests.get(f"{DASH}/api/status/{reqId}", timeout=10).json()
        print(f"   status={s['status']} tx={list((s.get('tx') or {}).keys())}")
        if s["status"] in ("approved", "refused", "error", "expired"):
            final = s
            break
    if final and final["status"] == "approved":
        print("   PASS: approved. explorer_links:")
        for k, v in (final.get("explorer_links") or {}).items():
            print(f"     {k}: {v}")
        return 0
    print(f"   FAIL: final={final}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
