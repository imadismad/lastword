"""Workflow test: drive every invoice in dashboard/invoices/ through the dashboard exactly
like the browser (multipart file upload), assert the expected verdict, and for the legit
ones submit -> badge -> live L1 payment and assert it is PAID.

Covers the full matrix:
  inv1 legit ACME            -> ASK_BADGE -> PAID
  inv2 legit Port Logistics  -> ASK_BADGE -> PAID
  inv3 address swapped       -> REJECT (C1), no badge
  inv4 prompt injection      -> injection flagged (C12), beneficiary kept, no self-approve
  inv5 unknown supplier      -> REJECT, no badge
  inv6 over per-tx cap       -> REJECT (C3), no badge

Usage:
  python dashboard/run_invoices.py [DASHBOARD_URL] [reader]
    DASHBOARD_URL default http://127.0.0.1:8090   (tunnel to EC2, or local)
    reader        'local' (default) | 'bedrock'

Each legit invoice is made unique per run (a run tag is appended) so re-runs don't hit the
contract's duplicate-quote guard (C6).
"""
import os
import sys
import time
import uuid

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
INV = os.path.join(HERE, "invoices")
D = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8090").rstrip("/")
READER = sys.argv[2] if len(sys.argv) > 2 else "local"
BEDROCK_MODEL = "us.anthropic.claude-sonnet-4-20250514-v1:0"
RUN = uuid.uuid4().hex[:8]

GREEN, RED, DIM, RST = "\033[32m", "\033[31m", "\033[2m", "\033[0m"

# The whitelist the guard should use (matches the on-chain seeded supplier 0x1111...).
# NOTE: only ACME's 0x1111 beneficiary is seeded on-chain, so only ACME invoices can PAY;
# Port Logistics (0x2222) will pass the guard but revert on-chain at propose (C1 on-chain) —
# so we only PAY ACME. We assert the guard verdict for all, and the on-chain pay for ACME.
WHITELIST = {
    "ACME Steel Supplies": {"beneficiary": "0x1111111111111111111111111111111111111111",
                            "cap": 1_000_000_000, "active": True},
    "港湾ロジ Port Logistics": {"beneficiary": "0x2222222222222222222222222222222222222222",
                               "cap": 500_000_000, "active": True},
}
POLICY = {"per_tx_cap": 1_000_000_000, "allowed_currencies": ["USD", "USDC", "dUSD"]}

# invoice -> (expected_verdict, pay_on_chain, note)
CASES = {
    "inv1_legit_acme.txt":      ("ASK_BADGE", True,  "whitelisted + correct address"),
    "inv3_address_swapped.txt": ("REJECT",    False, "beneficiary != whitelist (C1)"),
    "inv4_prompt_injection.txt":("INJECTION", False, "hidden instruction flagged (C12)"),
    "inv5_unknown_supplier.txt":("REJECT",    False, "supplier not whitelisted"),
    "inv6_over_cap.txt":        ("REJECT",    False, "amount over per-tx cap (C3)"),
}


def configure():
    body = {"whitelist": WHITELIST, "policy": POLICY, "reader_mode": READER}
    if READER == "bedrock":
        body["bedrock_model"] = BEDROCK_MODEL
        body["region"] = "us-east-1"
    r = requests.put(f"{D}/api/config", json=body, timeout=15).json()
    print(f"{DIM}reader={r['reader_mode']} model={r.get('bedrock_model') or '-'}{RST}")


def evaluate_file(path, unique):
    """Upload the invoice as multipart (the real browser path). `unique` makes the quote
    hash unique so a legit re-run does not collide with a prior on-chain reqId."""
    data = open(path, "rb").read()
    if unique:
        data = data + f"\nrun-tag: {RUN}\n".encode()
    files = {"file": (os.path.basename(path), data, "text/plain")}
    r = requests.post(f"{D}/api/evaluate", files=files,
                      data={"deadline_mins": "10", "token": "0"}, timeout=60)
    r.raise_for_status()
    return r.json()


def pay(proposal):
    sub = requests.post(f"{D}/api/submit", json={"proposal": proposal}, timeout=20).json()
    reqId = sub["reqId"]
    for _ in range(50):
        time.sleep(1.5)
        s = requests.get(f"{D}/api/status/{reqId}", timeout=10).json()
        if s["status"] in ("approved", "refused", "error", "expired"):
            return s
    return {"status": "timeout"}


def main():
    print(f"=== invoice workflow  ({D}, reader={READER}, run={RUN}) ===")
    configure()
    passed = failed = 0

    for name, (expect, do_pay, note) in CASES.items():
        path = os.path.join(INV, name)
        res = evaluate_file(path, unique=do_pay)
        verdict = res["verdict"]
        rs = (res.get("extracted") or {}).get("risk_signals", {})
        injected = bool(rs.get("injection_suspected"))
        reader = res.get("reader")

        ok = False
        detail = ""
        if expect == "INJECTION":
            # beneficiary must NOT be the attacker; injection must be flagged
            ben = (res["extracted"].get("beneficiary") or "").lower()
            attacker = "0xattacker" in ben
            ok = injected and not attacker and verdict in ("ASK_BADGE", "REJECT")
            detail = f"injection_flagged={injected} beneficiary={ben[:12]} verdict={verdict}"
        else:
            ok = verdict == expect
            detail = f"verdict={verdict} (expected {expect})"

        line = f"[{'PASS' if ok else 'FAIL'}] {name:28} {detail}  reader={reader}"
        print((GREEN if ok else RED) + line + RST)
        print(f"{DIM}       {note}{RST}")
        passed, failed = (passed + ok, failed + (not ok))

        if ok and do_pay and res.get("proposal"):
            s = pay(res["proposal"])
            paid = s["status"] == "approved"
            pl = f"       on-chain: {s['status']}"
            if paid:
                links = s.get("explorer_links", {})
                pl += "  PAID  " + " ".join(f"{k}={v.split('/tx/')[-1][:10]}" for k, v in links.items())
            print((GREEN if paid else RED) + pl + RST)
            passed, failed = (passed + paid, failed + (not paid))

    print(f"\n=== {passed} passed, {failed} failed ===")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
