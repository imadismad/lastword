"""Generate a Subnet-EVM genesis for the LASTWORD L1.

Pre-funds the same well-known test accounts the contracts/bridge/e2e use (anvil 0/1/2)
so the deployed chain behaves exactly like the local anvil dev chain. Enables recent
network upgrades so the secp256r1 (P-256) precompile at 0x100 is active.

Writes infra/genesis.json.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAIN_ID = 99999

# anvil well-known accounts (TEST ONLY, public)
ACCOUNTS = [
    "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",  # 0 deployer/vault
    "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",  # 1 agent
    "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",  # 2 bridge (gas)
    "0x90F79bf6EB2c4f870365E785982E1f101E93b906",  # 3 co-admin
    "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",  # 4 guardian
]

FUND = hex(10**24)  # 1,000,000 tokens (18 decimals) each

genesis = {
    "config": {
        "chainId": CHAIN_ID,
        "homesteadBlock": 0,
        "eip150Block": 0,
        "eip155Block": 0,
        "eip158Block": 0,
        "byzantiumBlock": 0,
        "constantinopleBlock": 0,
        "petersburgBlock": 0,
        "istanbulBlock": 0,
        "muirGlacierBlock": 0,
        "berlinBlock": 0,
        "londonBlock": 0,
        # Subnet-EVM network upgrades at genesis (0) so Durango/Etna/Granite features
        # - including the secp256r1 (P-256) precompile at 0x100 - are active from block 0.
        "subnetEVMTimestamp": 0,
        "durangoTimestamp": 0,
        "etnaTimestamp": 0,
        "feeConfig": {
            "gasLimit": 30000000,
            "minBaseFee": 25000000000,
            "targetGas": 15000000,
            "baseFeeChangeDenominator": 36,
            "minBlockGasCost": 0,
            "maxBlockGasCost": 1000000,
            "targetBlockRate": 2,
            "blockGasCostStep": 200000
        }
    },
    "alloc": {acct[2:]: {"balance": FUND} for acct in ACCOUNTS},
    "nonce": "0x0",
    "timestamp": "0x0",
    "extraData": "0x",
    "gasLimit": "0x1C9C380",
    "difficulty": "0x0",
    "mixHash": "0x0000000000000000000000000000000000000000000000000000000000000000",
    "coinbase": "0x0000000000000000000000000000000000000000",
    "number": "0x0",
    "gasUsed": "0x0",
    "parentHash": "0x0000000000000000000000000000000000000000000000000000000000000000"
}

out = os.path.join(ROOT, "infra", "genesis.json")
json.dump(genesis, open(out, "w"), indent=2)
print(f"wrote {out} (chainId={CHAIN_ID}, {len(ACCOUNTS)} prefunded accounts)")
