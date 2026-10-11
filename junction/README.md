# junction — the HP operator side (mesh → badge relay)

This is the receiving half of the LoRa link, meant to run on the **operator / HP machine**.
It turns the "everything on one laptop over TCP" demo into the real topology from the
cahier des charges: the agent proposes on the Dell, the request crosses **real LoRa radio**
to a second machine, and a badge there signs it.

```
  DELL (engineer I)                          LoRa radio                 HP (operator)
  ┌───────────────────────────┐                                  ┌──────────────────────────┐
  │ agent (Bedrock/Claude)     │                                  │ junction/mesh_junction.py │
  │   -> prepared proposal     │   node 1  ))))   PRIVATE_APP   (((( node 2 │   -> local badge          │
  │ bridge  BRIDGE_TRANSPORT=   │  (COM6)        I3 frame         (COMx) │       sim | serial:COMx   │
  │   mesh:COM6                 │  <<<<  I3 response frame  <<<<        │   P-256 signature         │
  │   -> propose/attest/approve │                                  └──────────────────────────┘
  │   -> live Avalanche L1      │
  └───────────────────────────┘
```

## What is REAL vs still simulated

| piece | status |
|-------|--------|
| AI reader (Amazon Bedrock / Claude) | **real** (on EC2) |
| Avalanche L1 + contract + payment | **real** (on-chain txs) |
| LoRa radio hop (Meshtastic) | **real** once a 2nd node runs this junction |
| Dell ↔ HP network separation | **real** once the junction runs on a 2nd machine |
| the badge **chip** (P-256) | **sim** until engineer N's `badge-fw` is flashed |

The junction never reads or forges the sealed I2 frame — it only moves bytes between the
radio and the badge, so swapping the sim badge for the real chip changes nothing else.

## Requirements for the realistic demo

1. **Two Meshtastic LoRa nodes** on the same channel/region:
   - node 1 on the Dell (COM6 — already a Meshtastic TLORA_V2_1_1P6),
   - node 2 on the HP machine (any Meshtastic node on a serial port).
   Pair them: `meshtastic --port COMx --ch-set ...` on both, or import the same channel
   URL (the Dell node already printed one via `python -m meshtastic --port COM6 --info`).
2. `pip install meshtastic` on the HP machine (+ `pyserial cryptography` for the sim badge).
3. The repo (or at least `proto/` + `badge-sim/` + `junction/`) on the HP machine.

## Run it (realistic path)

On the **HP machine** (node 2 on, e.g., COM5):
```
python junction/mesh_junction.py --dev COM5 --badge sim --auto        # sim badge today
python junction/mesh_junction.py --dev COM5 --badge serial:COM6       # real chip (badge-fw)
```

On the **Dell**, point the bridge at the mesh instead of TCP:
```
set BRIDGE_TRANSPORT=mesh:COM6
python -m lastword_bridge.main
```
Then drive the agent/dashboard as usual. The badge request now travels Dell → LoRa → HP →
badge → LoRa → Dell → contract. Status comes back to the agent exactly as before.

## Smoke test without a 2nd node

`infra/mesh_smoketest.py` (on the Dell) proves node 1 transmits a real I3 frame on
PRIVATE_APP. A full round-trip needs the 2nd node running this junction.

## When badge-fw arrives (engineer N)

Flash the chip, plug it into the HP machine, and start the junction with
`--badge serial:COMx`. Nothing else changes — the P-256 signature is then produced by the
real secure element, closing the last simulated gap.
