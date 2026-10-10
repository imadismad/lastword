# dashboard — agent operator console (FR-16, the full showpiece)

A web console on top of the existing agent + bridge. One screen to:

- **parametrize the agent** — edit the policy (per-tx / daily caps, allowed currencies) and
  the supplier whitelist live; choose the reader backend: **Local** (deterministic, no
  network) or **Amazon Bedrock** (Converse + forced-tool JSON schema + optional guardrail),
  with the model id / guardrail id / region;
- **drop in an invoice** — PDF, EML, or TXT; the agent reads it *in quarantine*;
- **see the prepared transaction** — extracted fields, the guard verdict
  (REJECT / ASK_DELIVERY / ASK_BADGE), the C1–C14 reasons, the risk score, the flags the
  badge will show, and the typed proposal — all **before** anything is approved;
- **send it to the badge → pay on the live L1** — the "Send to badge" button posts the
  prepared proposal to the bridge, which drives propose → attest → approve; the UI shows the
  three steps lighting up and links each tx into the block explorer.

The dashboard holds **no key and no payment power**. It calls the agent pipeline for reading
and the bridge I4 API for anything touching the badge or chain. It cannot approve — only the
badge signature + the contract can.

## Architecture

```
browser ──HTTP──> dashboard/server.py ──┬─ agent reader+guard (in-process)   [prepare]
   (UI)                                 └─ bridge I4 API  ──> badge ──> L1    [pay]
                                            (/proposals)       (P-256)   (contract)
```

## Run (local, Dell — reader falls back to Local since Bedrock is blocked here)

```powershell
# 1 anvil         2 badge-sim --auto     3 deploy a contract (see contracts/)
# 4 bridge  (set LASTWORD_CONTRACT_ADDRESS, BRIDGE_PRIVATE_KEY, AGENT_PRIVATE_KEY)
python -m lastword_bridge.main
# 5 dashboard
$env:BRIDGE_URL="http://127.0.0.1:8099"
python -m uvicorn dashboard.server:app --host 127.0.0.1 --port 8090
# open http://127.0.0.1:8090
```

## Run (EC2 — Bedrock reachable)

`infra/setup_dashboard.sh` installs it under pm2 next to the explorer. Reach it over the
same SSH tunnel (`-L 8090:127.0.0.1:8090`). Set `BEDROCK_MODEL_ID` (and optionally
`BEDROCK_GUARDRAIL_ID`) in the backend env, then flip the reader to **Bedrock** in the UI.

## Env

| var | default | meaning |
|-----|---------|---------|
| `BRIDGE_URL` | `http://127.0.0.1:8099` | the I4 bridge |
| `DASH_EXPLORER_URL` | `http://127.0.0.1:3000` | explorer base for tx links (`/tx/<hash>`) |
| `DASH_WHITELIST_FILE` | `agent/demo/whitelist.json` | initial whitelist |
| `BEDROCK_MODEL_ID`, `BEDROCK_GUARDRAIL_ID`, `AWS_DEFAULT_REGION` | — | Bedrock reader |

## API (what the UI calls)

- `GET /api/config` · `PUT /api/config` — read/update policy, whitelist, reader backend
- `POST /api/evaluate` (multipart file) · `POST /api/evaluate_text` — read + guard, returns
  extracted fields, verdict, reasons, score, flags, and the prepared proposal
- `POST /api/submit` — forward the prepared proposal to the bridge (→ badge → L1)
- `GET /api/status/{reqId}` — bridge status + explorer links per step
- `GET /api/bridge_health`

## Verified

`python dashboard/test_e2e.py` spins up anvil + badge-sim + a fresh contract + the bridge +
the dashboard, then drives the browser flow over HTTP:

- address-swap quote → **REJECT (C1)**, never reaches the badge;
- legit quote → **ASK_BADGE** → submit → propose/attest/approve → **PAID on-chain**
  (beneficiary +250000000), with explorer links for all three txs.
