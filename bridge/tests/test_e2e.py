"""End-to-end: deploy contract on anvil, provision badge-sim, run the full flow,
assert an on-chain payment. Requires anvil on :8545 and badge-sim on :8766 (--auto).

Run:  python -m pytest bridge/tests/test_e2e.py -s
It deploys a fresh contract each run using forge + a prepared env.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

import pytest
from web3 import Web3

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "proto", "src"))
sys.path.insert(0, os.path.join(ROOT, "bridge", "src"))

from lastword_proto import Command
from lastword_bridge.transport import TcpTransport
from lastword_bridge.gatewaykey import GatewayKey
from lastword_bridge.chain import ChainClient
from lastword_bridge.journal import Journal
from lastword_bridge.flow import Flow, Proposal, Status

RPC = os.environ.get("LASTWORD_RPC_URL", "http://127.0.0.1:8545")
BADGE_TCP = ("127.0.0.1", 8766)
FORGE = os.path.join(os.path.expanduser("~"), ".foundry", "bin", "forge.exe")
FRAME_KEY = hashlib.sha256(b"lastword-frame-key-poc").digest()
BADGE_ID = 40961

# anvil default account 0
DEPLOYER_PK = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
# anvil account 1 as the agent, account 2 as the bridge (gas only)
AGENT_ADDR = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
AGENT_PK = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
BRIDGE_ADDR = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"
BRIDGE_PK = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"


def _rpc_up() -> bool:
    try:
        return Web3(Web3.HTTPProvider(RPC)).is_connected()
    except Exception:
        return False


def _badge_pubkeys() -> dict:
    t = TcpTransport(*BADGE_TCP)
    cmd, data = t.exchange(Command.HELLO)
    assert cmd == Command.HELLO_OK and len(data) == 192
    return {"stock": data[:64].hex(), "daf": data[64:128].hex(), "duress": data[128:].hex()}


@pytest.mark.skipif(not _rpc_up(), reason="anvil not running on :8545")
def test_full_payment_flow():
    pub = _badge_pubkeys()
    gateway = GatewayKey.from_seed()  # matches badge-sim default gateway key

    supplier = "0x1111111111111111111111111111111111111111"

    env = os.environ.copy()
    env.update({
        "PRIVATE_KEY": DEPLOYER_PK,
        "AGENT_ADDR": AGENT_ADDR,
        "BRIDGE_ADDR": BRIDGE_ADDR,
        "COADMIN_ADDR": "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
        "GUARDIAN_ADDR": "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
        "DAF_QX": "0x" + pub["daf"][:64], "DAF_QY": "0x" + pub["daf"][64:],
        "STOCK_QX": "0x" + pub["stock"][:64], "STOCK_QY": "0x" + pub["stock"][64:],
        "DURESS_QX": "0x" + pub["duress"][:64], "DURESS_QY": "0x" + pub["duress"][64:],
        "SUPPLIER_ADDR": supplier, "SUPPLIER_CAP": "1000000000",
        "WHITELIST_DELAY": os.environ.get("WHITELIST_DELAY", "60"),
        "PARALLEL_CAP": "50000000",
    })

    # deploy (no --json; parse the broadcast file for addresses, which is robust)
    out = subprocess.run(
        [FORGE, "script", "script/Deploy.s.sol", "--rpc-url", RPC, "--broadcast"],
        cwd=os.path.join(ROOT, "contracts"), env=env, capture_output=True, text=True)
    assert out.returncode == 0, f"deploy failed:\n{out.stdout}\n{out.stderr}"

    lw_addr, usd_addr = _addrs_from_broadcast()
    assert lw_addr and usd_addr, "could not determine deployed addresses"
    print(f"\n[e2e] DemoUSD={usd_addr}  LastWord={lw_addr}")

    # fund + approve the vault (deployer is the vault) already done in Deploy.s.sol
    chain = ChainClient(RPC, lw_addr, BRIDGE_PK, agent_private_key=AGENT_PK)
    contract_bytes = bytes.fromhex(Web3.to_checksum_address(lw_addr)[2:])
    transport = TcpTransport(*BADGE_TCP)
    journal = Journal(os.path.join(ROOT, "bridge", "test_journal.jsonl"))

    # provision badge
    c, d = transport.exchange(Command.HELLO)
    assert c == Command.HELLO_OK
    prov = FRAME_KEY + chain.chain_id.to_bytes(8, "big") + contract_bytes + GatewayKey.from_seed().public_bytes()
    c, _ = transport.exchange(Command.PROVISION, prov)
    assert c == Command.PROV_OK

    flow = Flow(chain, gateway, journal, transport, FRAME_KEY, BADGE_ID,
                contract_bytes, chain.chain_id)

    # build a proposal
    from lastword_proto import Intent, Role
    intent = Intent(
        reqId=1001,
        beneficiary=bytes.fromhex(supplier[2:]),
        token=0, amount=250_000_000, nonce=1001,
        deadline=chain.w3.eth.get_block("latest")["timestamp"] + 600,
        quoteHash=hashlib.sha256(b"e2e-quote-1").digest(),
        flags=int(Role.DAF), policy=1,
    )
    p = Proposal(reqId=1001, intent=intent)

    w3 = chain.w3
    before = _balance(w3, usd_addr, supplier)

    flow.run(p)
    print(f"[e2e] final status: {p.status} detail={p.detail} tx={p.tx}")
    assert p.status == Status.APPROVED, f"flow did not reach APPROVED: {p.status} {p.detail}"

    after = _balance(w3, usd_addr, supplier)
    assert after - before == 250_000_000, f"payment not received: {after-before}"
    print(f"[e2e] PAID: beneficiary +{after-before} (demo USD)")

    ok, bad, msg = Journal.verify(os.path.join(ROOT, "bridge", "test_journal.jsonl"))
    assert ok, f"journal broken at {bad}: {msg}"
    print(f"[e2e] journal intact: {msg}")


def _addrs_from_broadcast() -> tuple[str | None, str | None]:
    """Read the latest forge broadcast file for the LastWord and DemoUSD addresses."""
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
        name = tx.get("contractName")
        addr = tx.get("contractAddress")
        if name == "LastWord":
            lw = Web3.to_checksum_address(addr)
        elif name == "DemoUSD":
            usd = Web3.to_checksum_address(addr)
    return lw, usd


def _balance(w3: Web3, token: str, who: str) -> int:
    erc20 = w3.eth.contract(address=Web3.to_checksum_address(token), abi=[
        {"type": "function", "name": "balanceOf", "stateMutability": "view",
         "inputs": [{"name": "a", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}]}])
    return erc20.functions.balanceOf(Web3.to_checksum_address(who)).call()
