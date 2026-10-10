# bridge — LASTWORD bridge (applicatif B)

Windows Python service. Exposes the local I4 API to the agent, drives the badge over
a transport (tcp/serial/mesh), submits to the contract via web3.py, and keeps a
hash-chained decision journal. The bridge key pays gas only and can approve nothing.

## What it does

```
agent --POST /proposals--> bridge --propose--> contract        (hard criteria on-chain)
                            bridge --REQUEST(stock)--> badge --RESPONSE(sig)--> attestDelivery
                            bridge --REQUEST(daf)--> badge   --RESPONSE(sig)--> approve --> PAID
```

Only statuses (`received|sent_stock|attested|sent_daf|approved|refused|expired|error`)
are ever returned to the agent — never raw frames, keys, or radio data.

## Run

```
# 1. local chain
anvil --port 8545
# 2. software badge (no hardware)
python badge-sim/badge_sim.py --tcp 127.0.0.1:8766 --auto
# 3. deploy the contract (see contracts/) with the badge pubkeys + gateway pubkey
# 4. bridge (reads .env for RPC, contract address, bridge key)
set BRIDGE_TRANSPORT=tcp:127.0.0.1:8766
python -m lastword_bridge.main
```

Transports (env `BRIDGE_TRANSPORT`):
- `tcp:127.0.0.1:8766` — badge-sim
- `serial:COM6[:115200]` — real badge over USB
- `mesh:COM6` — Meshtastic node 1 (PRIVATE_APP), relays to the badge via the HP junction

## Tests

- `bridge/tests/test_e2e.py` — full payment flow against anvil + badge-sim. Deploys a
  fresh contract, provisions the badge, posts a proposal, and asserts the beneficiary
  was paid and the journal verifies. **Green: `[e2e] PAID: beneficiary +250000000`.**

Run (with anvil on :8545 and badge-sim on :8766 --auto):
```
python -m pytest bridge/tests/test_e2e.py -s
```

## Journal (FR-12, §10)

`journal.jsonl` — append-only, hash-chained. `Journal.verify()` recomputes the chain
and locates the first altered entry. `Journal.merkle_root()` gives the root for
on-chain `anchor(root)` and the Fuji witness.

## Role separation

The agent proposes with its own EVM key (`onlyAgent`). The bridge submits attest/approve
with the bridge key (gas only). Approval authority is the P-256 badge signature the
contract verifies — not `msg.sender`. s is low-s normalized before every chain call.
