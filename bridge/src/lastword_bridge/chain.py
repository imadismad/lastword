"""Chain client (I5): submit propose/attestDelivery/approve/anchor via web3.py.

The bridge key pays gas only; it has no approval power on-chain (the contract checks
the P-256 badge signature, not msg.sender, for approval). s is already low-s normalized
before it reaches here.
"""
from __future__ import annotations

from web3 import Web3

# Avalanche Subnet-EVM is a PoA chain with a longer `extraData` header than L1 Ethereum.
# web3.py needs the PoA middleware to parse blocks. Import works across web3 v6/v7.
try:  # web3 >= 6.11 / 7.x
    from web3.middleware import ExtraDataToPOAMiddleware as _POA_MIDDLEWARE
    _POA_IS_CLASS = True
except Exception:  # older web3
    try:
        from web3.middleware import geth_poa_middleware as _POA_MIDDLEWARE
        _POA_IS_CLASS = False
    except Exception:
        _POA_MIDDLEWARE = None
        _POA_IS_CLASS = False

# Minimal ABI matching contracts/src/LastWord.sol (I5).
ABI = [
    {"type": "function", "name": "propose", "stateMutability": "nonpayable",
     "inputs": [{"name": "intent", "type": "bytes"}, {"name": "proofs", "type": "bytes"}],
     "outputs": [{"name": "reqId", "type": "uint32"}]},
    {"type": "function", "name": "attestDelivery", "stateMutability": "nonpayable",
     "inputs": [{"name": "reqId", "type": "uint32"}, {"name": "stockIntent", "type": "bytes"},
                {"name": "r", "type": "bytes32"}, {"name": "s", "type": "bytes32"}],
     "outputs": []},
    {"type": "function", "name": "approve", "stateMutability": "nonpayable",
     "inputs": [{"name": "reqId", "type": "uint32"}, {"name": "dafIntent", "type": "bytes"},
                {"name": "r", "type": "bytes32"}, {"name": "s", "type": "bytes32"}],
     "outputs": []},
    {"type": "function", "name": "cancel", "stateMutability": "nonpayable",
     "inputs": [{"name": "reqId", "type": "uint32"}], "outputs": []},
    {"type": "function", "name": "anchor", "stateMutability": "nonpayable",
     "inputs": [{"name": "root", "type": "bytes32"}], "outputs": []},
    {"type": "function", "name": "pause", "stateMutability": "nonpayable",
     "inputs": [], "outputs": []},
    {"type": "function", "name": "computeDigest", "stateMutability": "view",
     "inputs": [{"name": "intent", "type": "bytes"}], "outputs": [{"name": "", "type": "bytes32"}]},
    {"type": "function", "name": "requests", "stateMutability": "view",
     "inputs": [{"name": "", "type": "uint32"}],
     "outputs": [
        {"name": "state", "type": "uint8"}, {"name": "beneficiary", "type": "address"},
        {"name": "token", "type": "uint8"}, {"name": "amount", "type": "uint64"},
        {"name": "nonce", "type": "uint32"}, {"name": "deadline", "type": "uint32"},
        {"name": "quoteHash", "type": "bytes32"}, {"name": "digest", "type": "bytes32"},
        {"name": "flags", "type": "uint16"}, {"name": "policy", "type": "uint16"},
        {"name": "duress", "type": "bool"}]},
    {"type": "event", "name": "Approved", "inputs": [
        {"name": "reqId", "type": "uint32", "indexed": True},
        {"name": "beneficiary", "type": "address", "indexed": False},
        {"name": "amount", "type": "uint256", "indexed": False}]},
]


class ChainClient:
    def __init__(self, rpc_url: str, contract_addr: str, private_key: str,
                 agent_private_key: str | None = None):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        # inject PoA middleware for Avalanche Subnet-EVM (long extraData)
        if _POA_MIDDLEWARE is not None:
            try:
                if _POA_IS_CLASS:
                    self.w3.middleware_onion.inject(_POA_MIDDLEWARE, layer=0)
                else:
                    self.w3.middleware_onion.inject(_POA_MIDDLEWARE, layer=0)
            except (ValueError, Exception):
                pass  # already injected or incompatible; non-fatal
        self.acct = self.w3.eth.account.from_key(private_key)          # bridge (gas, attest/approve)
        # The agent proposes with its OWN key (role separation). If not provided,
        # fall back to the bridge key (single-key dev mode).
        self.agent_acct = (self.w3.eth.account.from_key(agent_private_key)
                           if agent_private_key else self.acct)
        self.contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(contract_addr), abi=ABI)
        self.chain_id = self.w3.eth.chain_id

    def _send(self, fn, acct=None):
        acct = acct or self.acct
        tx = fn.build_transaction({
            "from": acct.address,
            "nonce": self.w3.eth.get_transaction_count(acct.address),
            "gas": 1_000_000,
            "gasPrice": self.w3.eth.gas_price,
            "chainId": self.chain_id,
        })
        signed = acct.sign_transaction(tx)
        txh = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        rc = self.w3.eth.wait_for_transaction_receipt(txh, timeout=60)
        if rc.status != 1:
            raise RuntimeError(f"transaction reverted: {txh.hex()}")
        return rc

    def compute_digest(self, intent: bytes) -> bytes:
        return self.contract.functions.computeDigest(intent).call()

    def propose(self, intent: bytes, proofs: bytes = b""):
        # proposed by the AGENT account (onlyAgent on-chain)
        return self._send(self.contract.functions.propose(intent, proofs), self.agent_acct)

    def attest(self, reqId: int, intent: bytes, r: bytes, s: bytes):
        return self._send(self.contract.functions.attestDelivery(reqId, intent, r, s))

    def approve(self, reqId: int, intent: bytes, r: bytes, s: bytes):
        return self._send(self.contract.functions.approve(reqId, intent, r, s))

    def anchor(self, root: bytes):
        return self._send(self.contract.functions.anchor(root))

    def request_state(self, reqId: int) -> int:
        return self.contract.functions.requests(reqId).call()[0]
