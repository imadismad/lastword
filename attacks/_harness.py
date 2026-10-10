"""Shared harness for the LASTWORD attack demos.

Each attack script imports this to get a ready environment:
  - a running chain (anvil :8545 or the L1 via LASTWORD_RPC_URL),
  - a freshly deployed LastWord + DemoUSD (badge-sim pubkeys baked in),
  - a provisioned badge-sim on :8766,
  - a ChainClient + Flow wired exactly like the real bridge.

The attacks then try to subvert ONE layer and show the defence holds. Nothing here
weakens the system; the scripts only prove that tampered inputs are rejected.

Prereqs (same as bridge/tests/test_e2e.py):
  - badge-sim running:  python badge-sim/badge_sim.py --tcp 127.0.0.1:8766 --auto
  - a chain reachable at LASTWORD_RPC_URL (default anvil :8545), with the demo accounts.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

from web3 import Web3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "proto", "src"))
sys.path.insert(0, os.path.join(ROOT, "bridge", "src"))

from lastword_proto import Command, Intent, Role, digest as compute_digest  # noqa: E402
from lastword_bridge.transport import TcpTransport  # noqa: E402
from lastword_bridge.gatewaykey import GatewayKey  # noqa: E402
from lastword_bridge.chain import ChainClient  # noqa: E402
from lastword_bridge.journal import Journal  # noqa: E402
from lastword_bridge.flow import Flow, Proposal, Status  # noqa: E402

RPC = os.environ.get("LASTWORD_RPC_URL", "http://127.0.0.1:8545")
BADGE_TCP = ("127.0.0.1", 8766)
FORGE = os.path.join(os.path.expanduser("~"), ".foundry", "bin", "forge.exe")
FRAME_KEY = hashlib.sha256(b"lastword-frame-key-poc").digest()
BADGE_ID = 40961

DEPLOYER_PK = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
AGENT_ADDR = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
AGENT_PK = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
BRIDGE_ADDR = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"
BRIDGE_PK = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
SUPPLIER = "0x1111111111111111111111111111111111111111"

GREEN, RED, DIM, BOLD, RST = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


def banner(title: str):
    print(f"\n{BOLD}{'=' * 64}{RST}")
    print(f"{BOLD}  {title}{RST}")
    print(f"{BOLD}{'=' * 64}{RST}")


def defended(msg: str):
    print(f"{GREEN}  [DEFENDED] {msg}{RST}")


def breached(msg: str):
    print(f"{RED}  [BREACHED] {msg}{RST}")


def info(msg: str):
    print(f"{DIM}  {msg}{RST}")


def rpc_up() -> bool:
    try:
        return Web3(Web3.HTTPProvider(RPC)).is_connected()
    except Exception:
        return False


def badge_up() -> bool:
    try:
        t = TcpTransport(*BADGE_TCP, timeout=4.0)
        cmd, data = t.exchange(Command.HELLO)
        return cmd == Command.HELLO_OK and len(data) == 192
    except Exception:
        return False


def preflight():
    """Fail fast with a clear message if the chain or badge-sim is not up."""
    missing = []
    if not rpc_up():
        missing.append(f"chain at {RPC} (start anvil --port 8545, or open the L1 tunnel)")
    if not badge_up():
        missing.append("badge-sim on 127.0.0.1:8766 "
                       "(python badge-sim/badge_sim.py --tcp 127.0.0.1:8766 --auto)")
    if missing:
        print(f"{RED}Missing prerequisites:{RST}")
        for m in missing:
            print(f"  - {m}")
        sys.exit(2)


def badge_pubkeys() -> dict:
    t = TcpTransport(*BADGE_TCP)
    cmd, data = t.exchange(Command.HELLO)
    return {"stock": data[:64].hex(), "daf": data[64:128].hex(), "duress": data[128:].hex()}


def deploy_fresh() -> tuple[str, str]:
    """Deploy a fresh LastWord + DemoUSD with the badge-sim pubkeys. Returns (lw, usd)."""
    pub = badge_pubkeys()
    env = os.environ.copy()
    env.update({
        "PRIVATE_KEY": DEPLOYER_PK,
        "AGENT_ADDR": AGENT_ADDR, "BRIDGE_ADDR": BRIDGE_ADDR,
        "COADMIN_ADDR": "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
        "GUARDIAN_ADDR": "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
        "DAF_QX": "0x" + pub["daf"][:64], "DAF_QY": "0x" + pub["daf"][64:],
        "STOCK_QX": "0x" + pub["stock"][:64], "STOCK_QY": "0x" + pub["stock"][64:],
        "DURESS_QX": "0x" + pub["duress"][:64], "DURESS_QY": "0x" + pub["duress"][64:],
        "SUPPLIER_ADDR": SUPPLIER, "SUPPLIER_CAP": "1000000000",
        "WHITELIST_DELAY": os.environ.get("WHITELIST_DELAY", "0"),
        "PARALLEL_CAP": "50000000",
    })
    out = subprocess.run(
        [FORGE, "script", "script/Deploy.s.sol", "--rpc-url", RPC, "--broadcast"],
        cwd=os.path.join(ROOT, "contracts"), env=env, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"deploy failed:\n{out.stdout}\n{out.stderr}")
    lw, usd = _addrs_from_broadcast()
    if not (lw and usd):
        raise RuntimeError("could not determine deployed addresses")
    return lw, usd


def _addrs_from_broadcast() -> tuple[str | None, str | None]:
    bpath = os.path.join(ROOT, "contracts", "broadcast", "Deploy.s.sol")
    lw = usd = None
    newest = None
    for root, _dirs, files in os.walk(bpath):
        for f in files:
            if f == "run-latest.json":
                p = os.path.join(root, f)
                if newest is None or os.path.getmtime(p) > os.path.getmtime(newest):
                    newest = p
    if not newest:
        return None, None
    data = json.load(open(newest))
    for tx in data.get("transactions", []):
        if tx.get("contractName") == "LastWord":
            lw = Web3.to_checksum_address(tx.get("contractAddress"))
        elif tx.get("contractName") == "DemoUSD":
            usd = Web3.to_checksum_address(tx.get("contractAddress"))
    return lw, usd


def make_env(lw_addr: str):
    """Return (chain, flow, contract_bytes, journal) wired like the real bridge."""
    chain = ChainClient(RPC, lw_addr, BRIDGE_PK, agent_private_key=AGENT_PK)
    contract_bytes = bytes.fromhex(Web3.to_checksum_address(lw_addr)[2:])
    transport = TcpTransport(*BADGE_TCP)
    gateway = GatewayKey.from_seed()
    journal = Journal(os.path.join(ROOT, "attacks", "attack_journal.jsonl"))

    # provision the badge for this contract/chain
    chain_provision(transport, chain.chain_id, contract_bytes)
    flow = Flow(chain, gateway, journal, transport, FRAME_KEY, BADGE_ID,
                contract_bytes, chain.chain_id)
    return chain, flow, contract_bytes, journal


def chain_provision(transport, chain_id: int, contract_bytes: bytes):
    c, _ = transport.exchange(Command.HELLO)
    assert c == Command.HELLO_OK
    prov = FRAME_KEY + chain_id.to_bytes(8, "big") + contract_bytes
    c, _ = transport.exchange(Command.PROVISION, prov)
    assert c == Command.PROV_OK


def demo_daf_intent(chain, reqId: int, amount: int = 250_000_000) -> Intent:
    return Intent(
        reqId=reqId,
        beneficiary=bytes.fromhex(SUPPLIER[2:]),
        token=0, amount=amount, nonce=reqId,
        deadline=chain.w3.eth.get_block("latest")["timestamp"] + 600,
        quoteHash=hashlib.sha256(f"attack-quote-{reqId}".encode()).digest(),
        flags=int(Role.DAF), policy=1,
    )


def balance(w3, token: str, who: str) -> int:
    erc20 = w3.eth.contract(address=Web3.to_checksum_address(token), abi=[
        {"type": "function", "name": "balanceOf", "stateMutability": "view",
         "inputs": [{"name": "a", "type": "address"}],
         "outputs": [{"name": "", "type": "uint256"}]}])
    return erc20.functions.balanceOf(Web3.to_checksum_address(who)).call()

