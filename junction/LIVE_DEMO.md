# LASTWORD — 100% hardware Live Demo (Option A)

The "Live demo" tab in the dashboard drives the **real** path end to end: a Bedrock agent
reads the quote on the Dell, the I3 frame crosses a **real LoRa mesh** (Dell nugget →
battery relay → HP junction), a badge on the HP signs, and the signature returns over the
same mesh to pay on the live L1. No TCP shortcuts.

```
  Dell (node 1)              Nugget 2 (relay)            HP (node 3)
  dashboard + agent          battery, no PC              junction + badge
  + I4 bridge   ── LoRa ──►   routes frames   ── LoRa ──►  mesh_junction.py
  radio COM8                 (extends range)             badge: sim P-256 (→ hw chip)
        ▲                                                      │
        └──────────────── signature frame over the mesh ◄──────┘
```

The dashboard holds **no key and no payment power**. Only the badge signature + the
contract can approve.

## The three nuggets must share one channel

All three nuggets must use the **same primary channel + region + modem preset**, or they
can't hear each other. The Dell nugget (serial 5A5B009671, nugget-1) is the reference:

- region `EU_868`, preset `LONG_FAST`, hop 3
- channel URL: `https://meshtastic.org/e/#CgcSAQE6AggNEhQIATUAAKBBOANAA0gBUBtoAcAGAQ`

Inspect any nugget and align the others to that URL with `infra/mesh_setup.py`:

```powershell
# on whichever PC the nugget is plugged into
python infra/mesh_setup.py --info  COM8                 # see id / region / preset / url / peers
python infra/mesh_setup.py --url   COM8                 # print just the channel URL
python infra/mesh_setup.py --apply COMx "<channel-url>" # align another nugget
python infra/mesh_setup.py --ping  COMx                 # confirm reachable
```

The **battery relay** (nugget 2) just needs to be flashed with the same channel once, then
powered from the external battery — no PC during the demo. Align it on any PC first:
`python infra/mesh_setup.py --apply <relay COM> "<channel-url>"`, then unplug and run it on
the battery.

## 1 · Dell (node 1) — dashboard + agent + bridge + radio

The bridge owns the radio with the mesh transport; the dashboard reads it for status.

```powershell
# L1 reachable (SSH tunnel to the EC2 L1 RPC on :9650) — leave this running
ssh -N -L 9650:127.0.0.1:9650 -i infra\lastword-key.pem ubuntu@13.223.184.99

# bridge: transmit over the real mesh on COM8
$env:BRIDGE_TRANSPORT = "mesh:COM8"
.\.venv\Scripts\python.exe -m lastword_bridge.main      # or the project's bridge entrypoint

# dashboard: tell it which radio to show + where the bridge is
$env:LW_MESH_DEV = "COM8"
$env:BRIDGE_URL  = "http://127.0.0.1:8099"
.\.venv\Scripts\python.exe -m uvicorn dashboard.server:app --host 127.0.0.1 --port 8090
```

Open <http://127.0.0.1:8090>, click the **Live demo** tab.

### Simulated ↔ Real toggle

The Live demo tab has a **Badge transport** switch at the top:

- **Simulated** — the bridge talks to a local `badge-sim` over TCP (`BRIDGE_SIM_TRANSPORT`,
  default `tcp:127.0.0.1:8766`). No radio. Good for rehearsing the flow.
- **Real LoRa** — the bridge transmits the I3 frame over the mesh (`BRIDGE_REAL_TRANSPORT`,
  default `mesh:COM8`) to the HP junction + badge.

Flipping the switch calls `PUT /transport` on the bridge, which **re-provisions the badge**
on the new link (HELLO + PROVISION) — the TCP sim and the mesh/HP badge are different badge
instances. The mesh path takes ~15 s to provision. If the new transport can't be reached
(e.g. the HP junction isn't up yet), the switch fails cleanly and the bridge **stays on the
previous transport** — the toggle snaps back and shows why.

For the simulated side you need a badge-sim listening:

```powershell
python badge-sim/badge_sim.py --tcp 127.0.0.1:8766 --auto
```

Set the two targets per rig with `BRIDGE_SIM_TRANSPORT` / `BRIDGE_REAL_TRANSPORT` (or send
an explicit `{"spec":"mesh:COMx"}` to `PUT /transport`).

> Bedrock note: Bedrock is network-blocked on the Dell, so the Dell dashboard falls back to
> the **local deterministic reader** for the on-site read. For a demo that reads with the
> **real Bedrock agent**, run the dashboard on the EC2 (where Bedrock + the live L1 already
> run) and keep the hardware radio path by pointing its bridge at `mesh:COM8` over a reverse
> tunnel — or simply narrate that the EC2 dashboard already proves the Bedrock read while the
> Dell tab proves the LoRa hardware path. Pick per venue.

### What the Live demo tab shows

- **Topology** with a live status pill per node:
  - Dell radio: `up` (green) when the dashboard can read COM8; `busy` (amber) when the
    bridge is actively transmitting (that is the hardware path working, not an error).
  - Relay: `heard on mesh` once the radio has heard ≥ 1 peer.
  - HP junction: `heard on mesh` once ≥ 2 peers are heard (relay + HP).
- **Local radio** panel: node id, region, preset, hop, channel URL, and the peers heard.
- **Run the hardware flow**: paste a quote → *Read with agent* → *Send over the mesh →
  badge → pay on L1*, with per-step dots (read → propose → mesh/STOCK → mesh/DAF → paid)
  and explorer links for each on-chain tx.

## 2 · Nugget 2 — battery relay

No PC. Flash the shared channel once (step above), then power it from the external battery
somewhere between the Dell and the HP. It routes frames and extends range. Nothing else to
run.

## 3 · HP (node 3) — junction + badge

Plug nugget 3 into the HP, align its channel, then run the junction:

```powershell
python infra/mesh_setup.py --apply <HP COM> "https://meshtastic.org/e/#CgcSAQE6AggNEhQIATUAAKBBOANAA0gBUBtoAcAGAQ"
python junction/mesh_junction.py --dev <HP COM> --badge sim --auto
```

The junction opens its own node, listens for `PRIVATE_APP(256)` frames, hands each I3 frame
to the badge, and replies over the mesh. Backends:

- `--badge sim` — software P-256 badge (today)
- `--badge serial:COMx` — a real badge chip over USB, once `badge-fw` exists (track N)
- `--badge tcp:host:port` — a badge-sim running elsewhere on the HP

Drop `--auto` to approve manually at the badge for a dramatic "the human presses the button"
moment.

## Verify the mesh before the live run

1. Power the relay, start the HP junction.
2. On the Dell: `python infra/mesh_setup.py --info COM8` — you should see **both** peers
   (the relay and the HP node) in the peer list. The Live demo tab shows the same.
3. Run one quote through the Live demo tab. `approved` + an explorer link = the frame
   crossed the real LoRa mesh and the badge said the last word.

If the Dell radio shows `busy`: the bridge holds COM8 for transmit — expected while a flow
is running. The status read and the bridge can't open the same port at once; the dashboard
reports `busy` instead of erroring.
