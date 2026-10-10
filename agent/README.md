# agent — isolated reader + guard (applicatif A)

The AI agent decides *whether to ask*, never *whether to pay*. Its only verdicts are
`REJECT`, `ASK_DELIVERY`, `ASK_BADGE`. It holds no key and no payment power. It reaches
the bridge only through the I4 local API and can send only a typed proposal.

## Pieces

- **reader** — quarantined extraction, two interchangeable backends, same strict schema:
  - `LocalReader` — deterministic regex/heuristics, no network, no model (always works).
  - `BedrockReader` — Bedrock Converse with a **forced-tool JSON schema** + optional
    **guardrail** (prompt-attack filter). Auto-falls back to local on any Bedrock error.
  - A hidden instruction in the quote becomes `risk_signals.injection_suspected`, never
    an order. Every field keeps its provenance.
- **schema** — `READER_SCHEMA`; the reader output is validated against it before any use
  (anything off-schema is rejected, FR-02).
- **guard** — applies C1–C14, computes a 0..1 risk score, renders the verdict and the
  intent `flags` the badge displays. Only restricts. Hard criteria (C1,C3,C6,C8,C9) are
  re-checked on-chain by the contract.
- **agent** — read → validate → guard → (if ASK_BADGE) POST to the bridge; receives only
  a status back.

## Bedrock status (this network)

Bedrock is **unreachable from the Dell** (TLS to `bedrock*.amazonaws.com` is reset by a
network SNI filter; STS works, creds are valid — account `651408235101`,
`WSParticipantRole`). The agent therefore runs the **local reader** here. In the hybrid
PoC the agent runs on **EC2**, where Bedrock is reachable; the I4 interface is identical,
so nothing else changes. Use `--bedrock-model <id>` to enable it where reachable.

## Run

```
python -m lastword_agent.cli agent/demo/quote1_legit.txt \
    --whitelist agent/demo/whitelist.json --bridge http://127.0.0.1:8099
```

Demo quotes (`agent/demo/`): 2 legit (ASK_BADGE), 1 address-changed (REJECT, C1),
1 hidden-instruction injection (flagged, not executed), 1 unknown supplier (REJECT).

## Tests

- `agent/tests/test_agent.py` — reader/guard logic + demo dataset verdicts (7 tests, no network).
- `agent/tests/test_agent_bridge_e2e.py` — **agent → bridge HTTP → badge-sim → on-chain
  payment** (requires anvil + badge-sim). Green: `[agent->payment] PAID beneficiary +250000000`.
