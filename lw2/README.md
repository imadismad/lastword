# LASTWORD 2.0 — single-desk, real-LoRa demo

LASTWORD 2.0 keeps the frozen security core of v1 (`proto/`, `agent/`, `bridge/` Flow,
`contracts/`, `badge-fw/`). The demo now runs entirely on the Dell. Two LoRa nuggets
and the TROPIC01 badge are plugged into it, and every approval still crosses a real
868 MHz link.

```
                 ┌──────────────────────── Dell ────────────────────────────┐
 quote ─► agent  │  lw2 hub (FastAPI, :8100)                                │
 (untrusted)     │   ├─ isolated reader + guard (C1..C14) ── verdict only   │
                 │   ├─ LiveFlow: propose → attest → role check → approve   │──► Avalanche L1
                 │   └─ MeshRadio ── nugget-1 (COM6, persistent link)       │    (EC2, tunnel :9650)
                 │                     │  LoRa 868 MHz · PRIVATE_APP 256    │
                 │                     ▼  AES-256-GCM + P-256, end to end   │
                 │  badge station (separate process, NO key)                │
                 │   └─ nugget-3 (COM10) ⇄ USB ⇄ CDC badge / TROPIC01 (COM9)│
                 │                                                          │
                 │  web UI (React + Vite + Tailwind) ◄── WebSocket /ws      │
                 └──────────────────────────────────────────────────────────┘
```

## Separation of powers (unchanged from the spec)

| Component | Can | Cannot |
|---|---|---|
| Agent (reader + guard) | read the quote, return REJECT / ASK_DELIVERY / ASK_BADGE | touch the radio, hold a payment key, approve |
| Hub / bridge | pay gas, submit `propose` (agent key), `attest` and `approve` | approve anything: the contract only accepts a badge signature |
| Badge station | move sealed bytes between nugget-3 and the badge | read or change a frame (no key) |
| Badge (TROPIC01) | decrypt, check the gateway signature, show the intent, sign after the **physical** PIN | be driven by the network: the PIN comes only from the keypad |
| Contract | recompute the digest, verify P-256, pay | trust the radio, the hub or the agent |

The station runs as a separate process on purpose. In a product it moves onto the
badge, and the security does not change.

## What the UI shows live

- **Hardware path**: gateway, the air link and the badge station. Each frame is
  animated as it flies, with its measured RSSI, SNR, hops (`hopStart - hopLimit`),
  round-trip time and airtime (Semtech time-on-air for the active preset).
- **Agent**: reader output, risk score, each criterion C1..C14 as pass or fail, and any
  hidden instruction, which is flagged and never executed.
- **Approval pipeline**: propose, then STOCK over LoRa (human: Y → PIN → Y), attest, a
  role-separation check, DAF over LoRa, and finally approve & pay. Each step shows its
  duration and transaction. The role check is an `eth_call` of `approve` with the STOCK
  signature, and the contract must revert it. This is attack #3 of the spec, run on every
  payment.
- **Attack lab**: replays the last REQUEST, or flips one bit in it, on air. The badge
  must refuse both.
- **Evidence journal**: hash-chained (verified live) plus a Merkle root.

## Run

Prerequisites: the L1 tunnel `-L 9650` and `.env` (contract, RPC, `BRIDGE_PRIVATE_KEY`,
`AGENT_PRIVATE_KEY`). Plug in nugget-1, nugget-3 and the badge.

```powershell
.venv\Scripts\python.exe lw2\run.py             # opens hub + station; UI on http://127.0.0.1:8100
.venv\Scripts\python.exe lw2\run.py --badge sim # software P-256 badge (fallback, shown in the UI)
```

Devices are found by USB identity. COM numbers change on replug, so the lookup does
not rely on them:

| Device | How it is found | Override |
|---|---|---|
| nugget-1 (gateway) | CH34x serial `5A5B009671` | `LW_GATEWAY_PORT` / `LW_GATEWAY_NUGGET_SERIAL` |
| nugget-3 (station) | CH34x serial `5A5B009843` | `LW_STATION_PORT` / `LW_STATION_NUGGET_SERIAL` |
| badge | USB `08E6:4433` (cdc-badge-os) | `LW_BADGE_PORT` |

Timeouts: the station gives the human `JUNCTION_APPROVE_S=120` s per role. The hub
waits `LW_APPROVE_S=135` s, which adds radio round-trip slack.

UI development: `cd lw2\web && npm install && npm run dev`. The dev server proxies the hub.
`npm run build` writes `lw2/web/dist`, which is committed so the demo needs no Node.

## Honest limits

- Nuggets 1 and 3 sit on the same desk, so the link is **direct (0 hop)**, and the UI
  says so. The relay node (nugget-2) is not used in this setup.
- One person plays both roles (STOCK and DAF) on one badge. Each role has its own
  TROPIC01 key slot (28/29/30), and the role code is part of the signed intent.
- The chain is the EC2 Avalanche L1 reached through the SSH tunnel.
