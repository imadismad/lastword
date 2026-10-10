"""Run every LASTWORD attack demo and print a summary.

A1/A2 are agent-layer and need nothing. A3/A4/A5 are contract-layer and need a chain
(anvil :8545 or the L1 via LASTWORD_RPC_URL) plus badge-sim on :8766 --auto. If those
are missing, the contract-layer attacks are skipped (not failed).

    python attacks/run_all.py
"""
from __future__ import annotations

import importlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # for _harness + a*
sys.path.insert(0, os.path.join(ROOT, "proto", "src"))
sys.path.insert(0, os.path.join(ROOT, "agent", "src"))
sys.path.insert(0, os.path.join(ROOT, "bridge", "src"))

import _harness as H  # noqa: E402

AGENT_ATTACKS = ["a1_address_swap", "a2_prompt_injection"]
CHAIN_ATTACKS = ["a3_forged_signature", "a4_replay", "a5_role_confusion"]


def main():
    results = {}

    for name in AGENT_ATTACKS:
        mod = importlib.import_module(name)
        results[name] = mod.run()

    chain_ok = H.rpc_up() and H.badge_up()
    if not chain_ok:
        print(f"\n{H.DIM}  Skipping contract-layer attacks (A3-A5): need a chain at "
              f"{H.RPC} and badge-sim on :8766 --auto.{H.RST}")
        for name in CHAIN_ATTACKS:
            results[name] = None
    else:
        for name in CHAIN_ATTACKS:
            mod = importlib.import_module(name)
            try:
                results[name] = mod.run()
            except Exception as e:
                print(f"{H.RED}  {name} crashed: {type(e).__name__}: {e}{H.RST}")
                results[name] = 1

    H.banner("SUMMARY")
    worst = 0
    for name, rc in results.items():
        if rc is None:
            print(f"  {H.DIM}SKIP{H.RST}      {name}")
        elif rc == 0:
            print(f"  {H.GREEN}DEFENDED{H.RST}  {name}")
        else:
            print(f"  {H.RED}BREACHED{H.RST}  {name}")
            worst = 1
    print()
    sys.exit(worst)


if __name__ == "__main__":
    main()

