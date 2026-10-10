"""Attack A5 - role confusion / privilege escalation (contract layer).

Threat: the stock responsable (lower privilege) tries to stand in for the DAF. The bridge
takes the STOCK key's signature and submits it to approve() (the DAF step), hoping a valid
badge signature of any role is enough to release funds.

Defence: the two roles are different P-256 keys registered separately on-chain
(stockPub vs dafPub). approve() verifies against dafPub only. A signature made by the stock
key does not verify under the DAF public key, so approve() reverts. Separation of duties
holds even if the whole bridge is malicious.

Needs a chain + badge-sim.
    python attacks/a5_role_confusion.py
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
    H.banner("A5 - role confusion: stock key used for DAF approval (contract layer)")
    H.preflight()
    lw, usd = H.deploy_fresh()
    H.info(f"deployed LastWord={lw}")
    chain, flow, cbytes, _journal = H.make_env(lw)

    reqId = 7005
    daf = H.demo_daf_intent(chain, reqId)
    stock = _as_role(daf, Role.STOCK)

    H.info("1) legit propose + attest")
    chain.propose(daf.encode())
    ssig = flow._badge_sign(stock)
    chain.attest(reqId, stock.encode(), *ssig)

    H.info("2) attack: take a STOCK-key badge signature and submit it to approve() (DAF step)")
    # The badge signs by role: a STOCK-role intent is signed with the stock key. The
    # malicious bridge submits that stock-key signature to approve(), which verifies
    # against dafPub only. (The economic fields are identical; only the signer/role differ.)
    wrong_sig = flow._badge_sign(stock)

    before = H.balance(chain.w3, usd, H.SUPPLIER)
    try:
        # submit the DAF intent (what approve expects) but with a STOCK-key signature
        chain.approve(reqId, daf.encode(), *wrong_sig)
        after = H.balance(chain.w3, usd, H.SUPPLIER)
        if after > before:
            H.breached(f"stock key approved a DAF payment +{after - before} (escalation)")
            return 1
        H.breached("approve() did not revert (unexpected) but no payment moved")
        return 1
    except Exception as e:
        msg = str(e).splitlines()[0][:140]
        H.info(f"   approve() reverted: {msg}")
        after = H.balance(chain.w3, usd, H.SUPPLIER)
        if after == before:
            H.defended("stock-key signature fails under dafPub -> approve() reverts. "
                       "Separation of duties enforced on-chain, not by the bridge.")
            return 0
        H.breached("balance changed despite revert")
        return 1


if __name__ == "__main__":
    sys.exit(run())

