"""Agent -> bridge -> badge-sim -> on-chain payment, via the real HTTP I4 API.

Requires anvil on :8545 and badge-sim on :8766 (--auto). Deploys a fresh contract,
starts the bridge API in-process (threaded uvicorn), runs the agent against a legit
quote, and asserts the beneficiary was paid.

Run:  python -m pytest agent/tests/test_agent_bridge_e2e.py -s
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time

import pytest
from web3 import Web3

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in ("proto/src", "bridge/src", "agent/src"):
    sys.path.insert(0, os.path.join(ROOT, p))

from lastword_proto import Command
from lastword_bridge.transport import TcpTransport
from lastword_bridge.gatewaykey import GatewayKey
from lastword_bridge.chain import ChainClient
from lastword_bridge.journal import Journal
from lastword_bridge.flow import Flow
from lastword_bridge.api import create_app
from lastword_agent.agent import Agent
from lastword_agent.guard import Guard, DEFAULT_POLICY
from lastword_agent.reader import LocalReader

RPC = "http://127.0.0.1:8545"
BADGE_TCP = ("127.0.0.1", 8766)
FORGE = os.path.join(os.path.expanduser("~"), ".foundry", "bin", "forge.exe")
FRAME_KEY = hashlib.sha256(b"lastword-frame-key-poc").digest()
BADGE_ID = 40961
API_PORT = 8155

DEPLOYER_PK = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
AGENT_ADDR = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
AGENT_PK = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
BRIDGE_ADDR = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"
BRIDGE_PK = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"

WL = json.load(open(os.path.join(ROOT, "agent", "demo", "whitelist.json"), encoding="utf-8"))


def _rpc_up():
    try:
        return Web3(Web3.HTTPProvider(RPC)).is_connected()
    except Exception:
        return False


def _badge_pub():
    c, d = TcpTransport(*BADGE_TCP).exchange(Command.HELLO)
    assert c == Command.HELLO_OK
    return {"stock": d[:64].hex(), "daf": d[64:128].hex(), "duress": d[128:].hex()}


def _addrs():
    base = os.path.join(ROOT, "contracts", "broadcast", "Deploy.s.sol")
    newest = None
    for r, _d, fs in os.walk(base):
        for f in fs:
            if f == "run-latest.json":
                p = os.path.join(r, f)
                if newest is None or os.path.getmtime(p) > os.path.getmtime(newest):
                    newest = p
    data = json.load(open(newest))
    lw = usd = None
    for tx in data["transactions"]:
        if tx.get("contractName") == "LastWord":
            lw = Web3.to_checksum_address(tx["contractAddress"])
        if tx.get("contractName") == "DemoUSD":
            usd = Web3.to_checksum_address(tx["contractAddress"])
    return lw, usd


@pytest.mark.skipif(not _rpc_up(), reason="anvil not running on :8545")
def test_agent_to_payment():
    pub = _badge_pub()
    supplier_addr = WL["ACME Steel Supplies"]["beneficiary"]
    env = os.environ.copy()
    env.update({
        "PRIVATE_KEY": DEPLOYER_PK, "AGENT_ADDR": AGENT_ADDR, "BRIDGE_ADDR": BRIDGE_ADDR,
        "COADMIN_ADDR": "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
        "GUARDIAN_ADDR": "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
        "DAF_QX": "0x" + pub["daf"][:64], "DAF_QY": "0x" + pub["daf"][64:],
        "STOCK_QX": "0x" + pub["stock"][:64], "STOCK_QY": "0x" + pub["stock"][64:],
        "DURESS_QX": "0x" + pub["duress"][:64], "DURESS_QY": "0x" + pub["duress"][64:],
        "SUPPLIER_ADDR": supplier_addr, "SUPPLIER_CAP": "1000000000",
        "WHITELIST_DELAY": "60", "PARALLEL_CAP": "50000000",
    })
    out = subprocess.run([FORGE, "script", "script/Deploy.s.sol", "--rpc-url", RPC,
                          "--broadcast"], cwd=os.path.join(ROOT, "contracts"),
                         env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    lw_addr, usd_addr = _addrs()

    chain = ChainClient(RPC, lw_addr, BRIDGE_PK, agent_private_key=AGENT_PK)
    contract_bytes = bytes.fromhex(Web3.to_checksum_address(lw_addr)[2:])
    transport = TcpTransport(*BADGE_TCP)
    journal = Journal(os.path.join(ROOT, "bridge", "agent_e2e_journal.jsonl"))

    c, _ = transport.exchange(Command.HELLO)
    prov = FRAME_KEY + chain.chain_id.to_bytes(8, "big") + contract_bytes
    c, _ = transport.exchange(Command.PROVISION, prov)
    assert c == Command.PROV_OK

    gateway = GatewayKey.from_seed()
    flow = Flow(chain, gateway, journal, transport, FRAME_KEY, BADGE_ID,
                contract_bytes, chain.chain_id)
    app = create_app(flow)

    # start the bridge API in a background thread
    import uvicorn
    config = uvicorn.Config(app, host="127.0.0.1", port=API_PORT, log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)

    # run the agent against a legit quote; it will POST to the bridge
    guard = Guard(dict(DEFAULT_POLICY), WL)
    agent = Agent(f"http://127.0.0.1:{API_PORT}", guard, LocalReader())
    quote = open(os.path.join(ROOT, "agent", "demo", "quote1_legit.txt"),
                 encoding="utf-8").read()
    deadline = chain.w3.eth.get_block("latest")["timestamp"] + 600

    w3 = chain.w3
    erc = w3.eth.contract(address=usd_addr, abi=[
        {"type": "function", "name": "balanceOf", "stateMutability": "view",
         "inputs": [{"name": "a", "type": "address"}],
         "outputs": [{"name": "", "type": "uint256"}]}])
    before = erc.functions.balanceOf(Web3.to_checksum_address(supplier_addr)).call()

    res = agent.process(quote, deadline=deadline)
    print(f"\n[agent] verdict={res['verdict']} score={res['score']} posted={res['posted']}")
    assert res["verdict"] == "ASK_BADGE"
    assert res["posted"] is True
    reqId = res["bridge_response"]["reqId"]

    # wait for the flow (background thread in the bridge) to finish
    deadline_t = time.time() + 60
    status = None
    while time.time() < deadline_t:
        p = flow.proposals.get(reqId)
        if p and p.status.value in ("approved", "refused", "error"):
            status = p.status.value
            break
        time.sleep(0.3)
    assert status == "approved", f"flow status={status} detail={flow.proposals[reqId].detail}"

    after = erc.functions.balanceOf(Web3.to_checksum_address(supplier_addr)).call()
    assert after - before == 250_000_000, f"not paid: {after - before}"
    print(f"[agent->payment] PAID beneficiary +{after - before}")
    server.should_exit = True
