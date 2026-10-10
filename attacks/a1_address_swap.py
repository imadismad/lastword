"""Attack A1 - supplier address swap (agent layer, criterion C1).

Threat: an attacker edits a legitimate quote so the IBAN/wallet points at THEIR address,
keeping the supplier name and everything else intact ("man-in-the-quote").

Defence: the agent guard checks the extracted beneficiary against the whitelisted address
for that supplier (C1). A mismatch is a HARD fail -> REJECT. The request never reaches the
badge, so no signature is ever requested and nothing is proposed on-chain.

No chain or badge needed; this is pure agent logic.
    python attacks/a1_address_swap.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "proto", "src"))
sys.path.insert(0, os.path.join(ROOT, "agent", "src"))

from lastword_agent.guard import Guard, DEFAULT_POLICY  # noqa: E402
from _harness import banner, defended, breached, info  # noqa: E402

# A whitelist that pins ACME's payout address.
WHITELIST = {
    "ACME Components SAS": {
        "beneficiary": "0x1111111111111111111111111111111111111111",
        "cap": 1_000_000_000, "active": True,
    }
}


def run():
    banner("A1 - supplier address swap (C1, agent layer)")
    guard = Guard(policy=dict(DEFAULT_POLICY), whitelist=WHITELIST)

    legit = {
        "supplier_name": "ACME Components SAS",
        "beneficiary": "0x1111111111111111111111111111111111111111",
        "amount": 250_000_000, "currency": "USD", "risk_signals": {},
    }
    tampered = dict(legit)
    tampered["beneficiary"] = "0xdeadbeef00000000000000000000000000000000"  # attacker wallet
    tampered["risk_signals"] = {"address_changed": True}

    info("1) baseline: unmodified quote")
    v = guard.evaluate(legit, quote_hash="qh-legit")
    info(f"   verdict={v.verdict}  C1={v.reasons['C1']}  (would proceed to the badge)")
    assert v.verdict == "ASK_BADGE"

    info("2) attack: same supplier name, beneficiary swapped to the attacker's wallet")
    v = guard.evaluate(tampered, quote_hash="qh-tampered")
    info(f"   verdict={v.verdict}  C1={v.reasons['C1']}  score={v.score}")

    if v.verdict == "REJECT" and v.reasons["C1"] == "fail":
        defended("beneficiary != whitelisted address -> REJECT (C1). "
                 "Never reaches the badge; nothing proposed on-chain.")
        return 0
    breached("tampered beneficiary was accepted")
    return 1


if __name__ == "__main__":
    sys.exit(run())

