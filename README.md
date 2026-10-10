# LASTWORD

An AI agent reads a quote and *prepares* a payment; only an authorized human, with a
hardware TROPIC01 badge over an independent LoRa radio channel, can *approve* it; a
smart contract refuses anything that is not cryptographically proven.

Secure Horizons hackathon — Track 1 (Guardians of Value).

## The four separated powers

| Power | Who | Can | Cannot |
|-------|-----|-----|--------|
| Read untrusted document | isolated reader (Bedrock, no tools) | propose structured fields | authorize anything |
| Decide whether to ask | guard (deterministic rules + score) | restrict (REJECT / ASK_DELIVERY / ASK_BADGE) | authorize |
| Approve | DAF with TROPIC01 badge + PIN over LoRa | sign the payment intent (P-256) | — |
| Execute | smart contract (Avalanche L1) | verify signatures, release funds | be overridden by agent or cloud |

## Repository layout (monorepo)

```
proto/      Frozen SPEC + shared Python lib + vectors.json  (built first)
contracts/  Solidity (Foundry): the 3-step LASTWORD contract + tests
bridge/     Windows Python bridge: local API, chain submit, hash-chained journal
badge-sim/  Software badge in Python (software keys, same serial protocol)
badge-fw/   Fork of cdc-badge-os + LASTWORD module (ESP32-S3 / TROPIC01)
junction/   HP relay script: Meshtastic node 3 <-> badge
infra/      L1 Avalanche, WireGuard, EC2, Meshtastic config
witness/    EC2 witness: Fuji anchor + S3 object-lock
agent/      AI agent (Bedrock reader + guard)
attacks/    Demo attack scripts
```

## Status

Work in progress during the hackathon build window. See `proto/SPEC.md` for the
frozen interfaces (I1–I6) that every component depends on.

## Security notes

- No secrets in Git. Real keys live in a local `.env` (gitignored). Test keys live
  only in `proto/vectors.json`.
- The AI agent never holds a payment key. The contract is the only authority. The
  bridge key pays gas only and can approve nothing.
- Every model output is treated as data, never as an instruction.

## Known limits (declared)

- Two validators held by the same team are not a public chain; the Fuji anchor is
  what makes tampering externally detectable.
- Software-key fallbacks (badge, LoRa->IP) are announced on screen and in the demo
  when used; hardware guarantees are not demonstrated in that mode.
- See `proto/SPEC.md` and the cahier des charges §17 for unverified assumptions.
