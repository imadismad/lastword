"""Bridge entrypoint: wire config, provision the badge, serve the I4 API.

Transports:
  tcp:host:port     -> badge-sim (no hardware)
  serial:COMx[:baud]-> badge over direct USB
  mesh:COMx         -> Meshtastic node 1

Env (see .env.example):
  LASTWORD_RPC_URL, LASTWORD_CONTRACT_ADDRESS, BRIDGE_PRIVATE_KEY
  BRIDGE_TRANSPORT (default tcp:127.0.0.1:8766)
  BRIDGE_HOST (default 127.0.0.1), BRIDGE_PORT (default 8099)
  BADGE_ID (default 40961), FRAME_KEY (hex 32B; default derived from seed)
  GATEWAY_KEY_FILE (default .gateway.key, gitignored) or GATEWAY_SEED
"""
from __future__ import annotations

import hashlib
import os
import sys

import uvicorn
from web3 import Web3

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "proto", "src"))

from lastword_proto import Command
from lastword_proto.serial import unpack_message

from .api import create_app
from .chain import ChainClient
from .flow import Flow
from .gatewaykey import GatewayKey
from .journal import Journal
from .transport import make_transport

try:
    from dotenv import load_dotenv
    ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    ROOT = os.getcwd()

DEFAULT_FRAME_KEY = hashlib.sha256(b"lastword-frame-key-poc").digest()


def _frame_key() -> bytes:
    hx = os.environ.get("FRAME_KEY")
    return bytes.fromhex(hx) if hx else DEFAULT_FRAME_KEY


def provision_badge(transport, frame_key: bytes, chain_id: int, contract_addr: bytes):
    """HELLO (fetch pubkeys) then PROVISION (give frame key, chainId, contract)."""
    cmd, data = transport.exchange(Command.HELLO)
    if cmd != Command.HELLO_OK or len(data) != 192:
        raise RuntimeError(f"badge HELLO failed: cmd=0x{cmd:02x} len={len(data)}")
    pubkeys = {"stock": data[:64].hex(), "daf": data[64:128].hex(), "duress": data[128:].hex()}
    prov = frame_key + chain_id.to_bytes(8, "big") + contract_addr
    cmd, _ = transport.exchange(Command.PROVISION, prov)
    if cmd != Command.PROV_OK:
        raise RuntimeError(f"badge PROVISION failed: cmd=0x{cmd:02x}")
    return pubkeys


def build_flow() -> Flow:
    rpc = os.environ.get("LASTWORD_RPC_URL", "http://127.0.0.1:8545")
    contract = os.environ["LASTWORD_CONTRACT_ADDRESS"]
    pk = os.environ["BRIDGE_PRIVATE_KEY"]
    transport_spec = os.environ.get("BRIDGE_TRANSPORT", "tcp:127.0.0.1:8766")

    chain = ChainClient(rpc, contract, pk)
    gateway = (GatewayKey.from_seed(os.environ["GATEWAY_SEED"].encode())
               if os.environ.get("GATEWAY_SEED") else GatewayKey.from_seed())
    journal = Journal(os.path.join(ROOT, "bridge", "journal.jsonl"))
    transport = make_transport(transport_spec)
    frame_key = _frame_key()
    badge_id = int(os.environ.get("BADGE_ID", "40961"))
    contract_bytes = bytes.fromhex(Web3.to_checksum_address(contract)[2:])

    # provision the badge now so it can decrypt frames and recompute digests
    pubkeys = provision_badge(transport, frame_key, chain.chain_id, contract_bytes)
    print(f"[bridge] badge provisioned. pubkeys: stock={pubkeys['stock'][:12]}... "
          f"daf={pubkeys['daf'][:12]}... duress={pubkeys['duress'][:12]}...")
    print(f"[bridge] gateway pubkey: {gateway.public_hex()}")

    return Flow(chain, gateway, journal, transport, frame_key, badge_id,
                contract_bytes, chain.chain_id)


def main():
    flow = build_flow()
    app = create_app(flow)
    host = os.environ.get("BRIDGE_HOST", "127.0.0.1")
    port = int(os.environ.get("BRIDGE_PORT", "8099"))
    print(f"[bridge] serving I4 API on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
