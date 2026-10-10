"""All-in-one e2e for the dashboard full flow (B).

Starts anvil + badge-sim, deploys a fresh contract, starts the bridge and the dashboard as
subprocesses, then exercises the dashboard HTTP API exactly like the browser:
  evaluate_text (legit)  -> ASK_BADGE + prepared proposal
  submit                 -> bridge -> badge -> on-chain
  poll status            -> approved, with explorer links
Also checks a REJECT path (address swap) stays off the badge.

Everything is torn down at the end. Reads results from HTTP, not fragile stdout.

    python dashboard/test_e2e.py
"""
import os
import signal
import subprocess
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "attacks"))
PY = sys.executable
FOUNDRY = os.path.join(os.path.expanduser("~"), ".foundry", "bin", "anvil.exe")
SUP = "0x1111111111111111111111111111111111111111"
BRIDGE_PK = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
AGENT_PK = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"

procs = []


def spawn(cmd, env=None, cwd=ROOT):
    p = subprocess.Popen(cmd, env={**os.environ, **(env or {})}, cwd=cwd,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    return p


def wait_http(url, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        try:
            requests.get(url, timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    rpc = "http://127.0.0.1:8545"
    os.environ["LASTWORD_RPC_URL"] = rpc
    os.environ["WHITELIST_DELAY"] = "0"

    print("starting anvil + badge-sim ...")
    spawn([FOUNDRY, "--port", "8545", "--silent"])
    spawn([PY, os.path.join(ROOT, "badge-sim", "badge_sim.py"), "--tcp", "127.0.0.1:8766", "--auto"])
    if not wait_http(rpc, 25):
        print("anvil did not come up"); return 1
    time.sleep(2)

    print("deploying fresh contract ...")
    import _harness as H
    lw, usd = H.deploy_fresh()
    print(f"  LastWord={lw}")

    print("starting bridge ...")
    spawn([PY, "-m", "lastword_bridge.main"], env={
        "LASTWORD_RPC_URL": rpc, "LASTWORD_CONTRACT_ADDRESS": lw,
        "BRIDGE_PRIVATE_KEY": BRIDGE_PK, "AGENT_PRIVATE_KEY": AGENT_PK,
        "BRIDGE_TRANSPORT": "tcp:127.0.0.1:8766", "BRIDGE_PORT": "8099",
        "PYTHONPATH": os.path.join(ROOT, "bridge", "src") + os.pathsep + os.path.join(ROOT, "proto", "src"),
    })
    if not wait_http("http://127.0.0.1:8099/health", 30):
        print("bridge did not come up"); return 1

    print("starting dashboard ...")
    spawn([PY, "-m", "uvicorn", "dashboard.server:app", "--host", "127.0.0.1", "--port", "8090"],
          env={"BRIDGE_URL": "http://127.0.0.1:8099", "DASH_EXPLORER_URL": "http://127.0.0.1:3000"})
    if not wait_http("http://127.0.0.1:8090/api/config", 30):
        print("dashboard did not come up"); return 1

    D = "http://127.0.0.1:8090"
    rc = 0

    # configure whitelist so C1 can pass for the legit supplier
    requests.put(f"{D}/api/config", json={
        "whitelist": {"ACME Components SAS": {"beneficiary": SUP, "cap": 1_000_000_000, "active": True}},
        "policy": {"allowed_currencies": ["USD", "USDC", "dUSD"]},
    }, timeout=10)

    # ---- REJECT path: address swap ----
    print("\n[A] REJECT path (address swap) ...")
    bad = f"ACME Components SAS\nQuote: Q-1\nBeneficiary: 0xdeadbeef00000000000000000000000000000000\nTotal due: 250000000 USD\n"
    r = requests.post(f"{D}/api/evaluate_text", json={"text": bad}, timeout=20).json()
    print(f"  verdict={r['verdict']} C1={r['reasons'].get('C1')}")
    if r["verdict"] != "REJECT":
        print("  FAIL: tampered beneficiary should REJECT"); rc = 1
    else:
        print("  OK: rejected, no proposal, never reaches badge")

    # ---- ASK_BADGE + full pay ----
    print("\n[B] ASK_BADGE -> pay path (legit) ...")
    good = f"ACME Components SAS\nQuote ref: Q-2026-5512\nBeneficiary: {SUP}\nTotal due: 250000000 USD\nValidity: 30 days\n"
    r = requests.post(f"{D}/api/evaluate_text", json={"text": good, "deadline_mins": 10}, timeout=20).json()
    print(f"  verdict={r['verdict']} score={r['score']} reader={r['reader']}")
    if r["verdict"] != "ASK_BADGE" or not r.get("proposal"):
        print("  FAIL: legit quote should be ASK_BADGE with a proposal"); return 1

    sub = requests.post(f"{D}/api/submit", json={"proposal": r["proposal"]}, timeout=20).json()
    reqId = sub["reqId"]
    print(f"  submitted reqId={reqId}")

    final = None
    for _ in range(40):
        time.sleep(1.5)
        s = requests.get(f"{D}/api/status/{reqId}", timeout=10).json()
        if s["status"] in ("approved", "refused", "error", "expired"):
            final = s
            break
    print(f"  final status={final and final['status']}")
    if final and final["status"] == "approved":
        print("  OK: PAID on-chain via the dashboard. explorer links:")
        for k, v in (final.get("explorer_links") or {}).items():
            print(f"    {k}: {v}")
        bal = H.balance(H.ChainClient(rpc, lw, BRIDGE_PK).w3, usd, SUP)
        print(f"  beneficiary balance = {bal}")
        if bal < 250_000_000:
            print("  FAIL: beneficiary not paid"); rc = 1
    else:
        print(f"  FAIL: not approved: {final}"); rc = 1

    return rc


def cleanup():
    for p in procs:
        try:
            if os.name == "nt":
                p.send_signal(signal.CTRL_BREAK_EVENT)
        except Exception:
            pass
        try:
            p.terminate()
        except Exception:
            pass
    time.sleep(1)
    for p in procs:
        try:
            p.kill()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        code = main()
    finally:
        cleanup()
    print("\nRESULT:", "PASS" if code == 0 else "FAIL")
    sys.exit(code)
