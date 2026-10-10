"""Attack A4 - replay an already-approved approval (contract layer, state machine).

Threat: the bridge captures a VALID (intent, r, s) triple that the badge signed and that
already paid once. It re-submits the exact same approve() to pay the beneficiary a second
time (double-spend).

Defence: the contract tracks per-request state. Once a request reaches APPROVED/paid, its
state is terminal; a second approve() for the same reqId reverts (wrong state). The nonce /
reqId cannot be reused. The captured signature is worthless for a replay.

Needs a chain + badge-sim.
    python attacks/a4_replay.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "proto", "src"))
sys.path.insert(0, os.path.join(ROOT, "bridge", "src"))

import _harness as H  # noqa: E402
from lastword_proto import Role  # noqa: E402
from lastword_bridge.flow import _as_role  # noqa: E402


def run():
    H.banner("A4 - replay an approved payment (contract layer, state machine)")
    H.preflight()
    lw, usd = H.deploy_fresh()
    H.info(f"deployed LastWord={lw}")
    chain, flow, cbytes, _journal = H.make_env(lw)

    reqId = 7004
    daf = H.demo_daf_intent(chain, reqId)
    stock = _as_role(daf, Role.STOCK)

    H.info("1) legit full flow: propose -> attest -> approve (pays once)")
    chain.propose(daf.encode())
    ssig = flow._badge_sign(stock)
    chain.attest(reqId, stock.encode(), *ssig)
    dsig = flow._badge_sign(daf)              # the valid DAF signature we will try to replay

    before = H.balance(chain.w3, usd, H.SUPPLIER)
    chain.approve(reqId, daf.encode(), *dsig)
    after1 = H.balance(chain.w3, usd, H.SUPPLIER)
    H.info(f"   first approve paid +{after1 - before}; request state now terminal")
    if after1 - before <= 0:
        H.breached("the legitimate payment did not go through; cannot test replay")
        return 1

    H.info("2) attack: resubmit the SAME approve(reqId, intent, r, s) - captured valid sig")
    try:
        chain.approve(reqId, daf.encode(), *dsig)
        after2 = H.balance(chain.w3, usd, H.SUPPLIER)
        if after2 > after1:
            H.breached(f"replay paid again +{after2 - after1} (double-spend)")
            return 1
        H.breached("replay did not revert (unexpected) but no extra payment moved")
        return 1
    except Exception as e:
        msg = str(e).splitlines()[0][:140]
        H.info(f"   second approve() reverted: {msg}")
        after2 = H.balance(chain.w3, usd, H.SUPPLIER)
        if after2 == after1:
            H.defended("request state is terminal after payment; replaying a valid "
                       "signature reverts. No double-spend.")
            return 0
        H.breached("balance changed on replay despite revert")
        return 1


if __name__ == "__main__":
    sys.exit(run())

