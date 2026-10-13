# LASTWORD — demo runbook

> An AI agent reads a supplier quote and *prepares* a stablecoin payment. It can never
> release funds. Only a physical hardware badge (P‑256 signature) can approve, and a
> smart contract is the sole authority. The agent proposes; the badge says the last word.

This is the demo guide. Component internals live in each sub‑README
(`proto/`, `contracts/`, `bridge/`, `agent/`, `witness/`, `infra/`).

---

## 0. The three roles in the demo

| Role | Where | What it does |
|------|-------|--------------|
| **Agent (applicatif A)** | Dell (or EC2 for Bedrock) | reads the quote, applies guard C1–C14, can only emit a typed proposal — holds no key, no payment power |
| **Bridge (applicatif B)** | Dell, engineer **"I"** | local I4 API, drives the badge over tcp/serial/mesh, submits to the contract, keeps the hash‑chained journal — its key pays **gas only** |
| **Badge (applicatif C)** | hardware nugget, or `badge-sim` | holds the P‑256 keys, signs the sealed intent — the **only** approval authority |

The chain is a real **Avalanche L1** on EC2 (chainId 99999). Anvil is the local fallback.

---

## 1. What runs where

```
            Dell (engineer "I")                          EC2 (us-east-1)
  ┌────────────────────────────────┐          ┌──────────────────────────────┐
  │ agent  → bridge (I4 :8099)      │  SSH -L  │ Avalanche L1 RPC :9650        │
  │ badge-sim :8766  (or nugget COM6)│ ───────► │ block explorer :3000 / :3002  │
  │ RPC via tunnel → 127.0.0.1:9650 │          │ MongoDB (Docker)              │
  └────────────────────────────────┘          └──────────────────────────────┘
```

The Dell reaches the EC2 L1 RPC and the explorer through one SSH tunnel.

---

## 2. One‑time setup (Dell)

```powershell
# Python venv (already created at .venv). Foundry installed natively at %USERPROFILE%\.foundry\bin
# Copy env and fill in the sandbox creds + chain:
Copy-Item .env.example .env     # then edit (NEVER commit .env — it is gitignored)
```

`.env` for the **live L1 demo** needs:

```
AWS_DEFAULT_REGION=us-east-1
AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_SESSION_TOKEN=...   # STS sandbox
LASTWORD_RPC_URL=http://127.0.0.1:9650/ext/bc/2L6HsHiCxGeQFBoe5ezfz9ZBtNBZYGKC1QHrDCeQhLPYrW3iZj/rpc
LASTWORD_CHAIN_ID=99999
LASTWORD_CONTRACT_ADDRESS=<LastWord address printed by the deploy step>
BRIDGE_PRIVATE_KEY=0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a
WHITELIST_DELAY=0
```

Open the tunnel to EC2 (keep it running in its own terminal):

```powershell
ssh -N -i infra\lastword-key.pem -o StrictHostKeyChecking=no `
    -L 9650:127.0.0.1:9650 -L 3000:127.0.0.1:3000 -L 3002:127.0.0.1:3002 `
    ubuntu@13.223.184.99
```

---

## 3. The demo — software badge (works today, no hardware)

Four terminals on the Dell. This is the path proven green end‑to‑end on the live L1.

```powershell
# T1 — tunnel (section 2, left running)

# T2 — software badge
.\.venv\Scripts\python.exe .\badge-sim\badge_sim.py --tcp 127.0.0.1:8766 --auto

# T3 — bridge (reads .env; talks to badge over tcp, submits to the L1)
$env:BRIDGE_TRANSPORT = "tcp:127.0.0.1:8766"
.\.venv\Scripts\python.exe -m lastword_bridge.main

# T4 — agent: feed it a quote, it decides REJECT / ASK_BADGE and (if ASK_BADGE) proposes
.\.venv\Scripts\python.exe -m lastword_agent.cli agent\demo\quote1_legit.txt `
    --whitelist agent\demo\whitelist.json --bridge http://127.0.0.1:8099
```

Then show the payment on the **block explorer**: open <http://127.0.0.1:3000> (via the
tunnel) and point at the `LastWord` contract — the propose / attest / approve
transactions appear, all `status: 1`.

### The five demo quotes (`agent/demo/`)

| Quote | Expected verdict | Point it makes |
|-------|------------------|----------------|
| `quote1_legit.txt` | **ASK_BADGE** → PAID | happy path: badge signs, contract pays |
| `quote2_legit.txt` | **ASK_BADGE** → PAID | second legit supplier |
| `quote3_address_changed.txt` | **REJECT (C1)** | beneficiary ≠ whitelist → never reaches the badge |
| `quote4_injection.txt` | **flagged, not executed** | hidden "ignore instructions / pay me" → `injection_suspected`, not an order |
| `quote5_unknown_supplier.txt` | **REJECT** | supplier not whitelisted |

That contrast — legit pays, tampered/injected does not, and the *badge* is what gates it —
is the whole pitch.

### Or drive it all from the dashboard (the showpiece).

Instead of the CLI, run the operator console and do the whole thing in a browser:

```powershell
# with the bridge (T3) up:
$env:BRIDGE_URL="http://127.0.0.1:8099"
.\.venv\Scripts\python.exe -m uvicorn dashboard.server:app --host 127.0.0.1 --port 8090
# open http://127.0.0.1:8090
```

Drop an invoice (PDF/EML/TXT, e.g. `agent/demo/quote1_legit.txt`), watch the prepared
transaction appear (extracted fields, verdict, C1–C14, risk score), then **Send to badge →
pay on L1** and see propose/attest/approve light up with explorer links. See `dashboard/README.md`.

**Live on EC2 (with the real Bedrock reader):** the dashboard + bridge + badge-sim are
deployed on EC2 next to the L1 and explorer (`infra/deploy_dashboard_ec2.sh`). Tunnel to it
and open the UI:

```powershell
ssh -N -i infra\lastword-key.pem -L 8090:127.0.0.1:8090 -L 3000:127.0.0.1:3000 ubuntu@13.223.184.99
# open http://127.0.0.1:8090   (flip reader -> Bedrock; model us.anthropic.claude-sonnet-4-20250514-v1:0)
```

Verified end-to-end on EC2: **Amazon Bedrock (Claude Sonnet 4) read the invoice → guard →
badge → PAID on the live Avalanche L1**, three txs visible in the explorer. The pm2 stack
there is `lw-api / lw-indexer / lw-frontend / lw-badge / lw-bridge / lw-dashboard`.

---

## 4. Fastest proof (one command)

With the tunnel + badge‑sim up and `.env` pointed at the L1, the e2e test deploys a fresh
contract, runs the whole flow, and asserts the beneficiary was paid:

```powershell
.\.venv\Scripts\python.exe -m pytest bridge\tests\test_e2e.py -s
# => [e2e] PAID: beneficiary +250000000 (demo USD)   +   journal intact
```

Local‑only variant (no EC2): run `anvil --port 8545` and leave `.env` on `:8545` / chainId 31337.

---

## 5. Verify integrity (judges love this)

```powershell
# the decision journal is append-only + hash-chained; this finds any tampering
.\.venv\Scripts\python.exe -m lastword_bridge.verify_cli bridge\journal.jsonl
```

`witness/` anchors the Merkle root to Fuji + S3 for an external, independent timestamp.

### Show the attacks fail (the security half of the demo)

With the chain + badge-sim up (section 3), run the adversarial suite — each prints
`[DEFENDED]`:

```powershell
$env:LASTWORD_RPC_URL = "http://127.0.0.1:9650/ext/bc/2L6HsHiCxGeQFBoe5ezfz9ZBtNBZYGKC1QHrDCeQhLPYrW3iZj/rpc"
.\.venv\Scripts\python.exe attacks\run_all.py
```

Address swap and prompt injection are stopped at the agent (C1 / C12); forged signature,
replay, and role confusion are stopped by the contract (`P256.verify`, terminal state,
per-role pubkeys). A1/A2 need no chain. See `attacks/README.md`.

---

## 6. Status — what is DONE vs what is LEFT for the Dell / engineer "I"

### Done and verified
- `proto` (26 tests), `contracts` (14 forge tests), `bridge` e2e, `agent` (7 + integration),
  `witness`/journal (5) — all green.
- Full payment flow green on **anvil** *and* the **live Avalanche L1 on EC2**
  (propose → attest → approve, beneficiary paid, journal intact).
- Block explorer live on EC2, indexing the real LASTWORD payment txs (tag `explorer-v1`).
- Five adversarial attack demos, all `[DEFENDED]` (`attacks/`, tag `attacks-v1`).
- Mesh transport **smoke-tested on the real LoRa nugget** (COM6, Meshtastic node): our
  `MeshTransport` frames and transmits a real I3 message over LoRa.
- **Agent operator dashboard** (`dashboard/`): invoice → prepared transaction → badge → L1
  payment, driven from the browser; verified end-to-end locally AND **deployed on EC2 with
  the real Amazon Bedrock (Claude) reader**, paying on the live L1.
- Pushed to github.com/imadismad/lastword (tags: proto/contracts/bridge/agent/witness/infra/l1-live/explorer/attacks).

### Left for the Dell / engineer "I"
These are the remaining physical‑ and polish items; none block the software demo above.

1. **Mesh (Meshtastic) transport — SMOKE-TESTED on the real nugget.** The nugget on
   **COM6** is a LilyGO **TLORA_V2_1_1P6** running **Meshtastic 2.6.11** (node `!12b10afc`).
   `meshtastic` is now installed in the venv and `infra/mesh_smoketest.py` confirms our
   `MeshTransport` opens the node, frames a real I3 HELLO, and the radio transmits it on
   PRIVATE_APP (256). A **full round-trip** (RESPONSE back) needs a **second node flashed as
   the badge responder** — the only remaining hardware item. Run:
   `python infra\mesh_smoketest.py COM6`.
2. **Real badge over direct USB (`serial:COM6`).** The nugget is NOT running `badge-fw`
   (it runs Meshtastic). A HELLO over raw serial gets the ESP32 boot banner, not an
   I3 reply (`infra/probe_badge_serial.py` confirms). To use `BRIDGE_TRANSPORT=serial:COM6`
   you must flash engineer **N**'s `badge-fw` (not in this repo). The mesh path above is the
   intended radio transport anyway.
3. ~~FR‑16 operator / agent dashboard~~ — **DONE.** `dashboard/` is a web console to
   parametrize the agent (policy + whitelist + Local/Bedrock reader), drop in an invoice
   (PDF/EML/TXT), see the prepared transaction (extracted fields, verdict, C1–C14, risk,
   flags), and **Send to badge → pay on the live L1** with per-step explorer links. Verified
   end-to-end (`python dashboard\test_e2e.py`). Bedrock only works from EC2, so deploy there
   with `infra/setup_dashboard.sh` and reach it over the tunnel (`-L 8090:127.0.0.1:8090`).
4. ~~`attacks/` demo scripts~~ — **DONE.** `attacks/` has five scripted adversarial demos
   (address swap, prompt injection, forged signature, replay, role confusion); all five
   print `[DEFENDED]`. See `attacks/README.md`. Run `python attacks\run_all.py`.
5. **WireGuard client on the Dell** — optional. The SSH tunnel (section 2) is the working
   path; the WireGuard *server* is set up on EC2, but installing the Dell client needs one
   admin‑elevated command (`wireguard /installtunnelservice infra\lastword-wg0.conf`).

### Cost / teardown reminder
The EC2 instance (`i-06b1af13ef6af465a`, us-east-1) is **running** (~a few $/day). Tear down
when done: `python infra\provision_ec2.py --terminate`.
