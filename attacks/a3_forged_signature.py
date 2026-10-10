"""Attack A3 - forged badge signature (contract layer).

Threat: the bridge is fully compromised. It skips the badge entirely and submits approve()
with a signature it made up (random r,s), hoping msg.sender or a plausible-looking blob is
enough.

Defence: approval authority is NOT msg.sender. The contract recomputes the digest from the
submitted intent and runs P256.verify(dafPub, digest, r, s). A forged signature does not
verify under the registered DAF public key, so approve() reverts. No payment occurs.

Needs a chain + badge-sim (to deploy with real pubkeys and to run the legit steps up to
approve). Only the final approve is forged.
    python attacks/a3_forged_signature.py
"""
from __future__ import annotations

import os
import secrets
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "proto", "src"))
sys.path.insert(0, os.path.join(ROOT, "bridge", "src"))

import _harness as H  # noqa: E402
from lastword_proto import Role, P256_N  # noqa: E402
from lastword_bridge.flow import _as_role  # noqa: E402


def run():
    H.banner("A3 - forged badge signature (contract layer, P256.verify)")
    H.preflight()
    lw, usd = H.deploy_fresh()
    H.info(f"deployed LastWord={lw}")
    chain, flow, cbytes, _journal = H.make_env(lw)

    reqId = 7003
    daf = H.demo_daf_intent(chain, reqId)
    stock = _as_role(daf, Role.STOCK)

    H.info("1) legit propose + attest (badge signs the stock step honestly)")
    chain.propose(daf.encode())
    ssig = flow._badge_sign(stock)
    chain.attest(reqId, stock.encode(), *ssig)

    H.info("2) attack: approve() with a FORGED signature (random r,s) - badge bypassed")
    r_fake = ((int.from_bytes(secrets.token_bytes(32), "big") % (P256_N - 1)) + 1).to_bytes(32, "big")
    s_fake = ((int.from_bytes(secrets.token_bytes(32), "big") % (P256_N - 1)) + 1).to_bytes(32, "big")

    before = H.balance(chain.w3, usd, H.SUPPLIER)
    try:
        chain.approve(reqId, daf.encode(), r_fake, s_fake)
        after = H.balance(chain.w3, usd, H.SUPPLIER)
        if after > before:
            H.breached(f"forged signature was accepted; beneficiary paid +{after - before}")
            return 1
        H.breached("approve() did not revert (unexpected), but no payment moved")
        return 1
    except Exception as e:
        msg = str(e).splitlines()[0][:140]
        H.info(f"   approve() reverted: {msg}")
        after = H.balance(chain.w3, usd, H.SUPPLIER)
        if after == before:
            H.defended("forged signature fails P256.verify under the DAF pubkey -> "
                       "approve() reverts, no payment. msg.sender is irrelevant.")
            return 0
        H.breached("balance changed despite revert")
        return 1


if __name__ == "__main__":
    sys.exit(run())

