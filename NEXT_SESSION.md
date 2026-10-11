# LASTWORD — resume runbook (next session)

This captures exact state + the remaining steps so a fresh session can finish the 100%
hardware demo without rediscovering anything. **Start a NEW Kiro session before using this**
— the previous session's PowerShell got wedged (cwd drift + many orphaned background procs
+ serial-port contention). A fresh session clears all of it.

Latest pushed commit: **`301f440`** on `main` (github.com/imadismad/lastword).

---

## 1. What is DONE and verified

- **Software spine** (proto/contracts/bridge/agent/witness) tested + pushed; attacks 5/5.
- **EC2 Avalanche L1 + explorer + real Bedrock dashboard** live (see §5 for addresses).
- **Dashboard "Live demo" tab** (100% hardware page) + **Simulated↔Real transport toggle**
  built, committed, and **deployed to EC2** (commit `301f440`, `_LIVE_SEEN` present there).
- **Honest status pills**: relay/HP pills no longer lie from stale node-DB; they reflect
  real over-the-air detection (`live` = heard a packet in the last 5 min) and only go
  "proven" after a real mesh round-trip.
- **Mesh channel fix PROVEN**: nugget-1 (`0afc`, COM6) hears nugget-2 (`0d60`) live after
  aligning channels — captured `RX from !12b10d60 NODEINFO_APP rssi=-22 snr=10.0`.

## 2. The three nuggets (serials are stable; COM numbers are NOT)

| node short | node id        | USB serial     | fw      | role                         |
|------------|----------------|----------------|---------|------------------------------|
| `0afc`     | `!12b10afc`    | `5A5B009671`   | 2.6.11  | **nugget-1** = Dell radio    |
| `0d60`     | `!12b10d60`    | `5A5B008992`   | 2.7.15  | **nugget-2** = battery relay |
| `0d98`     | `!12b10d98`    | (3rd nugget)   | —       | **nugget-3** = HP junction   |

**Shared channel URL (all three must match):**
`https://meshtastic.org/e/#CgcSAQE6AggNEhQIATUAAKBBOANAA0gBUBtoAcAGAQ`
Region EU_868, preset LONG_FAST, hop 3. nugget-1 and nugget-2 are ALREADY on this channel.
**nugget-3 still needs it applied.**

COM numbers change on replug. Always re-detect by serial:
```powershell
Get-PnpDevice -Class Ports -PresentOnly | ? InstanceId -match 'VID_1A86' | fl FriendlyName,InstanceId
```
`5A5B009671`→nugget-1, `5A5B008992`→nugget-2.

## 3. Serial-port rules (critical — caused most of the pain)

- Each nugget = one COM port, **exclusive**. Only ONE process may hold it at a time.
- The dashboard holds its radio (`LW_MESH_DEV`) for ~15–24 s per poll (open is slow +
  a live-listen window). Do NOT run `mesh_setup.py` / `mesh_probe.py` against the SAME port
  while the dashboard is up — you'll get `PermissionError(13) Accès refusé`. Stop the
  dashboard first, or target a different port.
- To free a stuck port: `Get-Process python | Stop-Process -Force`, then if still stuck,
  **physically unplug/replug** the nugget (clears Windows error-31 / stale handles).
- Confirm a port is free: open+close test —
  `$sp=New-Object System.IO.Ports.SerialPort('COM6',115200);$sp.Open();$sp.Close()`.

## 4. Finish the Dell demo path (#3) — bring-up, in order

Goal: Dell runs dashboard + bridge + L1 tunnel so propose→attest→approve→pay works on the
live L1, with the badge over EITHER local TCP sim (rehearsal) or the LoRa mesh (real).

### 4a. L1 tunnel (needed for ALL on-chain work)
```powershell
ssh -N -i infra\lastword-key.pem -o ExitOnForwardFailure=yes -L 9650:127.0.0.1:9650 ubuntu@13.223.184.99
```
Verify it forwards (run `infra/l1_check.py` — expects a block number). If `urlopen` throws,
the tunnel is NOT up; re-check SSH/security-group before anything else.

### 4b. OPEN QUESTION to resolve first — agent authorization on the EC2 contract
The bridge's `propose` is `onlyAgent`. A Dell-run bridge must sign `propose` with a key the
EC2 LastWord contract (`0xc5a5c42992decbae36851359345fe25997f5c42d`) recognizes as the
agent. Options:
  1. Reuse the SAME agent/bridge keys the EC2 bridge uses (read them from the EC2
     `/home/ubuntu/.env` or pm2 dump) → guaranteed authorized.
  2. Or check the contract's `agent()` getter and, if it's a demo key we hold
     (`0x70997970C5...` acct1), set `AGENT_PRIVATE_KEY=0x59c6995e...` locally.
Do NOT skip this — if the agent key is wrong, the flow dies at `propose` with a revert and
it looks like a mesh problem when it isn't.

### 4c. .env on the Dell (already partly set)
Already set this session: `LASTWORD_CONTRACT_ADDRESS=0xc5a5c42992decbae36851359345fe25997f5c42d`,
`LASTWORD_RPC_URL=http://127.0.0.1:9650/ext/bc/2L6HsHiC.../rpc`, `LASTWORD_CHAIN_ID=99999`,
`BRIDGE_PRIVATE_KEY` present. Still need (per 4b): `AGENT_PRIVATE_KEY`, and matching
`FRAME_KEY`/`GATEWAY_SEED` if the EC2 badge was provisioned with non-defaults (defaults are
fine for a FRESH local badge-sim).

### 4d. Rehearsal mode (Simulated — no radio, proves agent→bridge→badge→L1)
```powershell
# badge-sim on TCP
.\.venv\Scripts\python.exe .\badge-sim\badge_sim.py --tcp 127.0.0.1:8766 --auto
# bridge in sim transport
$env:BRIDGE_TRANSPORT="tcp:127.0.0.1:8766"; $env:BRIDGE_PORT="8099"
.\.venv\Scripts\python.exe -m lastword_bridge.main
# dashboard (point at the local bridge; omit LW_MESH_DEV so it doesn't fight the radio)
$env:BRIDGE_URL="http://127.0.0.1:8099"; $env:LW_MESH_DEV="COM6"
.\.venv\Scripts\python.exe -m uvicorn dashboard.server:app --host 127.0.0.1 --port 8090
```
Open http://127.0.0.1:8090 → Live demo → run an invoice in **Simulated**. Green all the way
= Dell half works; only the radio+HP remain.

### 4e. Real mesh mode (needs HP up — see §6)
Flip the toggle to **Real LoRa** (BRIDGE_REAL_TRANSPORT defaults to `mesh:COM6`). The toggle
re-provisions the badge over the mesh; if the HP junction isn't answering it fails cleanly
and reverts to Simulated (by design).

> **Port contention note for real mode:** the bridge (mesh:COM6) and the dashboard's radio
> status reader BOTH want COM6. Run the dashboard withOUT `LW_MESH_DEV` while the bridge
> owns the radio, OR accept that the dashboard radio panel shows "busy (bridge owns it)"
> during a real submit — that's expected and already handled in the UI.

## 5. EC2 facts

- Instance `i-06b1af13ef6af465a` (us-east-1), IP `13.223.184.99`, key `infra/lastword-key.pem`.
- SSH: `ssh -n -i infra\lastword-key.pem -o StrictHostKeyChecking=no -o BatchMode=yes -o ConnectTimeout=20 ubuntu@13.223.184.99`
- pm2 services online: lw-api(:3002), lw-indexer, lw-frontend(:3000), lw-badge, lw-bridge(:8099), lw-dashboard(:8090).
- L1 RPC path: `/ext/bc/2L6HsHiCxGeQFBoe5ezfz9ZBtNBZYGKC1QHrDCeQhLPYrW3iZj/rpc`
- Contract LastWord: `0xc5a5c42992decbae36851359345fe25997f5c42d`
- Repo on EC2: `/home/ubuntu/lastword` (updated via `git archive` tarball, NOT git clone).
- Bedrock creds `/home/ubuntu/bedrock.env` (chmod 600, TEMP STS — **they expire**; regenerate
  `infra/bedrock.env` and `pm2 restart lw-dashboard --update-env` when Bedrock 500s).
- **Redeploy dashboard to EC2** (same recipe used this session):
  ```powershell
  git archive --format=tar.gz -o deploy.tar.gz HEAD dashboard
  scp -i infra\lastword-key.pem deploy.tar.gz ubuntu@13.223.184.99:/home/ubuntu/deploy.tar.gz
  ssh -n -i infra\lastword-key.pem ubuntu@13.223.184.99 "cd /home/ubuntu/lastword; tar xzf /home/ubuntu/deploy.tar.gz; pm2 restart lw-dashboard --update-env; rm -f /home/ubuntu/deploy.tar.gz"
  ```
  Use `;` not `&&` in the remote command (a `grep -c` returning 0 exits non-zero and aborts `&&` chains).

## 6. HP side (nugget-3 + junction) — the real blocker for the final round-trip

On the HP, with nugget-3 plugged in:
```powershell
# 1. align nugget-3 to the shared channel (find its COM first, by serial)
python infra/mesh_setup.py --apply <HP COM> "https://meshtastic.org/e/#CgcSAQE6AggNEhQIATUAAKBBOANAA0gBUBtoAcAGAQ"
# 2. run the junction (software badge today; serial:COMx once badge-fw exists)
python junction/mesh_junction.py --dev <HP COM> --badge sim --auto
```
Then on the Dell, flip the Live-demo toggle to Real LoRa and run an invoice. `approved` +
explorer link = the frame crossed the real mesh and the badge said the last word. Only THEN
do the relay/HP pills go green ("path proven" / "badge replied").

## 7. Diagnostic helpers (in infra/, committed)

- `infra/mesh_setup.py --info|--url|--apply|--ping COMx` — inspect/align a nugget.
- `infra/mesh_probe.py COMx [listen_s]` — node DB (with lastHeard) + live-listen; prints RX.
- `infra/mesh_hear.py COMx [s] [outfile]` — listen, flag when nugget-2 (`0d60`) is heard live.
- `infra/l1_check.py` — L1 reachability + contract-has-code via the tunnel.
- `infra/poll_live.py` — poll the dashboard until nugget-2 shows live (DON'T run while the
  dashboard is also polling the same port — they contend).

## 8. Shell gotchas on this Dell (so next session doesn't relearn them)

- `execute_pwsh` echoes/mangles commands and often returns exit -1 even on success — **read
  results from files**, not stdout. Write with `Out-File -Encoding utf8` or from Python
  `io.open(...,encoding='utf-8')`.
- PowerShell `>` redirect writes UTF-16 → corrupts binary; use `Out-File -Encoding utf8`.
- Plain `ssh`/`Start-Sleep`+ssh can wedge the shell — use `ssh -n -o BatchMode=yes -o ConnectTimeout`.
- Multi-line `python -c` and nested quotes get mangled — **write a .py file and run it**.
- The shell's cwd drifts between calls — always use ABSOLUTE paths for scripts AND output files.
- Background `uvicorn`/tunnels launched via the process tool are more reliable than inline;
  but kill orphans between runs (`Get-Process python,ssh | Stop-Process -Force`) or ports stay held.

## 9. Teardown reminder

EC2 runs ~$/day. When done: `python infra/provision_ec2.py --terminate`.
