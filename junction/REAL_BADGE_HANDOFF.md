# Real badge over the mesh — handoff notes (N → I)

Status after today's HP-side session: the LoRa path works end to end for **HELLO**
and **PROVISION** against the real badge-fw chip. We saw, live, on the junction:

```
<- 7B  frame (HELLO)     -> 199B response   # badge returned its 3 role pubkeys
<- 131B frame (PROVISION)-> 7B   response   # PROV_OK: badge got frameKey/chainId/addr/gatewayPub
```

What has **not** happened yet: a real **REQUEST** (~172 B) reaching the badge. The
badge screen stayed blank the whole time because no REQUEST ever arrived — only the
dashboard's connectivity **HELLO probes** and the Real-mode **re-PROVISION**. To get
a signature we need an actual invoice submitted (`POST /proposals` → propose → the
bridge sends the stock + DAF REQUEST frames over the mesh).

## Do this to get a real signature

1. **Submit an invoice** in the dashboard Live-demo tab (Real LoRa), or `POST
   /proposals` directly. HELLO/PROVISION alone never raise the badge screen.
2. When a REQUEST reaches the badge, the **e-paper shows the approval screen**
   (role, beneficiary, amount). On the badge: **Y → PIN `123456` → Y**, twice —
   once for the STOCK attestation, once for the DAF approval.

## Two blockers to fix first (both on the junction side)

### A. `--badge serial` needs branch `wanbl/badge-fw` merged
Your `SerialBadge` (commit `b0deb3e`) does `import badge_serial_test` from
`badge-fw/tools/`. That file lives **only on branch `wanbl/badge-fw`**, not on
`main`. On `main` today, `--badge serial:COMx` raises
`SystemExit: --badge serial needs badge-fw/tools`. **Merge `wanbl/badge-fw` into
`main`** (it's the firmware branch, already pushed) so the junction can import it.

### B. Re-AUTH on an already-armed badge → the `got 8B` failures
`handle()` calls `bst.enter_binary()` on **every** frame, and `enter_binary` does an
unconditional `AUTH` + `lastword-bin`. But the badge's byte interceptor stays armed
~120 s after the first frame. Re-sending `AUTH` while armed is **swallowed as binary**
→ `no valid I3 reply (got 8B)` (we hit this live). Fix: **probe first** — send a
HELLO; if a valid reply comes back the badge is already in binary mode, so skip
AUTH/`lastword-bin`. The probe-first logic is on branch `wanbl/junction-serial`
(`SerialBadge._probe_binary` / `_enter_binary`); fold it into the shared
`badge_serial_test.enter_binary` so both the harness and the junction get it.

### C. 30 s approval window is too short for a human
`JUNCTION_APPROVE_S=30` barely covers reading the e-paper and typing a PIN under
pressure. Use **90–120 s** (`set JUNCTION_APPROVE_S=120`). The badge only answers a
REQUEST *after* the human presses Y → PIN → Y, so the junction must wait that long.

## Frame-size cheat sheet (to read the junction logs)
- `7B`   = HELLO (connectivity probe / handshake)
- `131B` = PROVISION (frameKey 32 + chainId 8 + contractAddr 20 + gatewayPub 64 = 124 B payload)
- `~172B`= REQUEST (I2 frame: intent 79 + gateway sig 64, sealed) — **this is the one that raises the screen**
- `199B` = HELLO_OK reply (3×64 role pubkeys)
- `~98B` = RESPONSE reply (reqId + decision + badge P-256 signature)

## Verified facts (so we don't re-litigate)
- The badge signs with the **hardware TROPIC01** (slots 28/29/30 = stock/DAF/duress),
  low-s P-256, verified against the DAF pubkey. Proven over USB and now PROVISIONed
  over LoRa.
- Junction replies **broadcast** (`^all`) — DMs hit NO_CHANNEL/PKI. Correct, kept.
- PROVISION is **124 B** (gateway pubkey included) on both bridge and badge. Aligned.
- nugget-3 (HP) is on the shared LASTWORD channel (EU_868 / LONG_FAST / hop 3).

## The two SerialBadge versions — reconcile
Both of us rewrote `junction/mesh_junction.py`'s `SerialBadge`:
- **yours** (`b0deb3e`, main): thin, reuses `badge_serial_test.py` — cleaner, but
  needs fix B (probe-first) and the badge-fw branch merged (fix A).
- **mine** (`wanbl/junction-serial`): self-contained, has probe-first + per-session
  re-arm, no dependency on badge-fw/tools.
Suggestion: keep **yours** (reuse the single source of truth) once badge-fw is on
main, and port my probe-first into `badge_serial_test.enter_binary`. I can do that
merge if you want — ping me.

## Status on `main` (I → N)
- **A. done** — `wanbl/badge-fw` merged into `main`; `--badge serial` imports
  `badge-fw/tools/badge_serial_test.py`.
- **B. done** — probe-first lives in `badge_serial_test.enter_binary` (new
  `probe_binary`: HELLO first, AUTH + `lastword-bin` only if not armed, re-probe before
  waiting out the idle timeout). The junction's `SerialBadge` keeps the port open, enters
  binary once and re-arms only after a failure (your session model).
- **C. done** — `JUNCTION_APPROVE_S` defaults to 120 s; the bridge waits 135 s
  (`BRIDGE_MESH_APPROVE_S`) to cover the radio round-trip; the Live-demo tab follows
  the flow for 6 min.
- The EC2 contract now holds the TROPIC01 role keys (stock/DAF/duress), so the real
  badge's signatures pass `attest` / `approve` on-chain.
