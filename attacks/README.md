# attacks — adversarial demos (the "it still can't pay" proof)

Each script stages one concrete attack and shows the matching LASTWORD defence holds.
They are the security half of the demo: the happy path shows a payment goes through; these
show that tampering, injection, forgery, replay, and privilege escalation do **not**.

Every script prints `[DEFENDED]` (green) or `[BREACHED]` (red) and exits `0` / `1`.
Nothing here weakens the system — the scripts only prove that bad inputs are rejected.

## The five attacks

| # | Attack | Layer | Defence | Needs chain? |
|---|--------|-------|---------|--------------|
| **A1** | supplier address swap (man-in-the-quote) | agent guard | C1: beneficiary ≠ whitelisted → REJECT, never reaches the badge | no |
| **A2** | prompt injection hidden in the quote | agent reader+guard | quarantined reader: instruction becomes a *data* signal (C12), not an order; beneficiary unchanged; agent can't self-approve | no |
| **A3** | forged badge signature (bridge bypasses the badge) | contract | `approve()` runs `P256.verify` under the DAF pubkey; random r,s fails → revert, no payment. msg.sender is irrelevant | yes |
| **A4** | replay an already-approved payment (double-spend) | contract | request state is terminal after payment + nonce used → second `approve()` reverts | yes |
| **A5** | role confusion: stock key used for the DAF step | contract | `approve()` verifies against `dafPub` only; a stock-key signature fails → revert. Separation of duties is on-chain, not in the bridge | yes |

A1/A2 run anywhere (pure agent logic). A3/A4/A5 drive a real contract.

## Run

```powershell
# agent-layer only (no setup):
.\.venv\Scripts\python.exe attacks\a1_address_swap.py
.\.venv\Scripts\python.exe attacks\a2_prompt_injection.py

# everything, incl. contract-layer (needs a chain + badge-sim):
#   T1: anvil --port 8545          (or open the EC2 L1 tunnel and set LASTWORD_RPC_URL)
#   T2: python badge-sim\badge_sim.py --tcp 127.0.0.1:8766 --auto
$env:LASTWORD_RPC_URL = "http://127.0.0.1:8545"; $env:WHITELIST_DELAY = "0"
.\.venv\Scripts\python.exe attacks\run_all.py
```

`run_all.py` skips A3–A5 (does not fail them) if no chain/badge-sim is up, so A1/A2 always
give a result. Against the **live Avalanche L1**, point `LASTWORD_RPC_URL` at the tunnelled
RPC instead of anvil — the defences are identical.

## Verified

All five print `[DEFENDED]` against anvil + badge-sim (and the contract‑layer three are the
same contract that runs on the live L1):

```
DEFENDED  a1_address_swap
DEFENDED  a2_prompt_injection
DEFENDED  a3_forged_signature
DEFENDED  a4_replay
DEFENDED  a5_role_confusion
```

Each contract-layer attack first runs the honest steps (so the setup is real), then performs
exactly one forbidden action and asserts it reverts with no funds moved.
