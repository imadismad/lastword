# LASTWORD — Badge + LoRa handoff (everything we learned)

This is the single document to read before touching the **hardware badge
(TROPIC01 / cdc-badge-os)** or the **LoRa mesh (Meshtastic nuggets)**. It captures
what works, what we proved on real hardware, every trap we hit, and the exact
commands/recipes — so the next session doesn't rediscover any of it.

Branches in play:
- **`wanbl/badge-fw`** — the firmware: `badge-fw/` (cdc-badge-os submodule +
  `mod_lastword` + host tools). Pushed.
- **`wanbl/junction-serial`** — junction adapted to the real badge (probe-first
  `SerialBadge`) + `junction/REAL_BADGE_HANDOFF.md`. Pushed.
- **`origin/main`** — the collaborator's spine (bridge, dashboard, mesh helpers,
  his own `SerialBadge` in `b0deb3e`).

> **First action for whoever resumes: merge `wanbl/badge-fw` into `main`.** The
> junction's `--badge serial` path imports `badge-fw/tools/badge_serial_test.py`,
> which lives only on that branch. Without it, `--badge serial:COMx` dies with
> `SystemExit: --badge serial needs badge-fw/tools`.

---

## 1. What is PROVEN on real hardware

- **mod_lastword runs on the badge** (`MODULE LIST` shows `[14] mod_lastword
  enabled [ON]`), 3 role keys generated **in the TROPIC01** (ECC slots 28/29/30 =
  stock/DAF/duress), confirmed via `TR01 SLOTS` → `[28] [29] [30] Used`.
- **Hardware P-256 signature end to end over USB**: HELLO → PROVISION → REQUEST →
  human approval (e-paper + keypad PIN) → signature **verified against the DAF
  pubkey, low-s**, reproducibly. Screen showed `ROLE : DAF (simule)` (no "software
  key" banner), so it is the real secure element. This is assumption §17.1 proven.
- **Over LoRa**: HELLO and PROVISION proven end to end (Dell → nugget-1 → relay →
  nugget-3/HP → badge → broadcast reply → Dell). `PROV_OK` returned. A full REQUEST
  over the mesh is the only remaining step (see §7).

## 2. The badge: hardware facts

- Two chips: **ESP32-S3** (the MCU we flash) + **TROPIC01** (secure element, we
  NEVER flash it, only talk to it over SPI via libtropic). The P-256 private keys
  are generated inside the TROPIC01 and never leave it.
- Firmware = **cdc-badge-os** (github.com/krim404/cdc-badge-os), added as a submodule
  under `badge-fw/cdc-badge-os`. Our code is `badge-fw/mod_lastword/` (OUTSIDE the
  submodule) + a 4-file fork patch (`badge-fw/patches/lastword.patch`, applied by
  `badge-fw/patches/apply.sh`). Docs: https://krim404.github.io/cdc-badge-os/
- Board = CDC Badge v1.1: e-paper, 12-key keypad (`0-9`, `Y`, `N`), USB-C.
- Default badge PIN: **`123456`**. ECC slot map: 0=PIN attestation, 1-3 GPG, 5-8
  PIV, **9-27 FIDO2 (shrunk from 9-30 by our patch)**, **28-30 LASTWORD**, 31 plugins.

## 3. Flashing the badge (recipe that works)

```
# ALWAYS back up the whole flash first (16 MB). Never erase_flash.
esptool.py --chip esp32s3 --port <PORT> read_flash 0 0x1000000 badge_backup.bin
# build + flash (from badge-fw/cdc-badge-os, after apply.sh + submodule init)
pio run -e cdc_badge_usb
pio run -e cdc_badge_usb -t upload --upload-port <PORT>
```

**Reflash trap:** a running badge refuses upload with `No serial data received`.
Put it in download mode FIRST, over the console:
```
AUTH 123456   <newline>
BOOTLOADER    <newline>
```
then flash. (The USB-Serial-JTAG boot logs do NOT appear on the CDC console port;
diagnose boot via `MODULE LIST` / `ERROR_LOG` / `TR01 SLOTS` instead.)

Build prerequisites once: `git submodule update --init --recursive
badge-fw/cdc-badge-os`, then `badge-fw/patches/apply.sh`. The WAMR nested submodule
must be initialised too (we hit a build fail when it wasn't).

## 4. The serial console protocol (how to talk to mod_lastword)

The badge exposes a **line-oriented text console** AND a **binary I3 channel**.
Hard-won rules:

1. **Secure serial is ON.** Every command except `PING`/`AUTH` needs a prior
   `AUTH 123456`. The session times out after **5 min idle**.
2. **Bare LF terminators, never CRLF.** With `\r\n` the badge executes on `\r` and
   the trailing `\n` is swallowed as the first binary byte (corrupts the next
   frame). Send `b"...\n"`.
3. **Enter the binary channel** with the text command `lastword-bin`. It installs a
   command-registry **ByteInterceptor**: from then on every serial byte goes raw to
   the proto engine (no line parsing).
4. **The interceptor stays armed ~120 s** (idle timeout — we raised it from 3 s,
   which was shorter than a single HELLO and broke things). Consequence: a NEW
   process can inherit an already-armed badge. Re-sending `AUTH` while armed gets
   swallowed as binary → the infamous **`got 8B`** failure. **Fix = probe-first**:
   send a HELLO; if a valid I3 reply comes back, the badge is already armed, skip
   AUTH/`lastword-bin`. (Implemented in `wanbl/junction-serial`'s `SerialBadge`.)
5. **Logs are interleaved.** Reading pubkeys opens/closes TROPIC01 sessions, which
   print `[I][TR01] ...` lines on the SAME port, and the real reply (e.g. 199 B
   HELLO_OK) arrives AFTER ~4.5 s of them. The frame reader must skip text and scan
   for the first COBS+CRC-valid I3 frame (see `badge_serial_test.read_cobs_frame`).

Reference implementation of all of this: **`badge-fw/tools/badge_serial_test.py`**
(validated on hardware). Subcommands: `hello` (reads the 3 role pubkeys), `sign`
(full HELLO→PROVISION→REQUEST→verify, needs a human to approve).

## 5. The I3 wire protocol (frozen in proto/SPEC.md)

Each message: `COBS( cmd(1) | len(2 BE) | data | CRC-16/CCITT(2 BE) ) + 0x00`.
Commands: `HELLO 0x01` / `HELLO_OK 0x81` (3×64 pubkeys), `PROVISION 0x02` /
`PROV_OK 0x82`, `REQUEST 0x03` / `RESPONSE 0x83` / `REFUSED 0x84`.

**PROVISION is 124 bytes**: `frameKey(32) || chainId(8 BE) || contractAddr(20) ||
gatewayPub(64)`. The gateway pubkey was a late addition — without it the badge has
no key to verify the gateway signature and REFUSEs every REQUEST (`BAD_GATEWAY_SIG`).
Both bridge and badge-sim were aligned to 124 B.

**Frame-size cheat sheet** (to read junction logs):
- `7B` = HELLO · `131B` = PROVISION · `~172B` = REQUEST (raises the e-paper screen!)
- `199B` = HELLO_OK · `~98B` = RESPONSE (reqId + decision + badge P-256 sig)

**The digest the badge signs** (must match the contract byte-for-byte):
`SHA-256("LASTWORD-v1" || chainId(8 BE) || contractAddr(20) || intent(79))`.
OpenZeppelin P256 rejects high-s, so the signer emits any s and it is **normalized
to low-s** before the contract sees it.

## 6. The async approval flow (why it's event-driven)

The main loop runs `SerialCmd::process()` (our interceptor) AND `ui_process()`
(keypad + e-paper views) on the **same FreeRTOS task**. So the badge must NOT block
in the interceptor waiting for a PIN — that freezes the UI task and deadlocks (FIDO2
can block on a semaphore only because CTAP-HID is a separate task; we are not).

Therefore REQUEST handling is **non-blocking**: `handleRequest` decrypts, verifies
the gateway sig, stashes the pending request, and calls `beginApproval()` which
pushes an `InfoView` (role + beneficiary + amount) with Y/N callbacks, then returns.
On **Y** it pushes a `PinEntryView`; on PIN success it signs the stashed digest with
the role key and emits the RESPONSE via the stored sink. The PIN comes from the
**physical keypad**, never the serial line — that's the whole point of the project.

**So: a REQUEST only replies AFTER a human presses Y → PIN → Y on the badge.** Give
the host side a long timeout (we use 90-120 s; the collaborator's 30 s is too short).

## 7. What's left to see the FULL mesh payment

The chain works through PROVISION over LoRa. The missing piece is a **real REQUEST**:
HELLO/PROVISION are just the dashboard's connectivity probes + the Real-mode
re-provision; they never raise the screen. To get a signature over the mesh:

1. Merge `wanbl/badge-fw` into `main` (so `--badge serial` can import the tools).
2. Fold **probe-first** into `badge_serial_test.enter_binary` (kills the `got 8B`),
   and set `JUNCTION_APPROVE_S=120`.
3. On the HP: `python infra/hp_nugget3.py --port <nugget> --run --badge
   serial:<badge>` (pairs nugget-3, then runs the junction).
4. On the Dell: **submit a real invoice** in the Live-demo tab (Real LoRa) — not a
   connectivity test. That triggers propose → the bridge sends the STOCK REQUEST
   then the DAF REQUEST over the mesh.
5. On the badge, for EACH request: **Y → PIN `123456` → Y** (stock, then DAF).
6. Expected: `approved` + an explorer link; the junction logs a `~172B` in and a
   `~98B` RESPONSE out.

## 8. The LoRa mesh (Meshtastic nuggets)

Three T3 LoRa32 (TLORA_V2_1_1P6) nuggets, **region EU_868, preset LONG_FAST, hop 3**:
- nugget-1 `!12b10afc` (serial `5A5B009671`) = Dell radio
- nugget-2 `!12b10d60` (serial `5A5B008992`) = battery relay (no PC)
- nugget-3 `!12b10d98` = HP junction (plugged into the badge machine)

They must share the **same channel URL** (PSK + region + preset + freq offset).
COM/tty numbers change on replug — match by USB serial (CH34x, VID 1A86). On Linux
the badge is `/dev/ttyACM0` (ESP32-S3 native USB) and the nugget `/dev/ttyACM1`
(CH34x); confirm by plugging one at a time.

Current shared channel (collaborator's Dell is the reference now; nugget-3 aligned
to it this session):
`https://meshtastic.org/e/#CgcSAQE6AggNEhQIATUAAKBBOANAA0gBUBtoAcAGAQ`

Helpers (`infra/`): `mesh_setup.py --info|--url|--apply|--ping COMx`,
`mesh_hear.py COMx [s]` (listen + RSSI/SNR), `hp_nugget3.py` (detect + pair + run).
Alignment proven live: nugget-3 heard the Dell at **rssi -38..-47 dBm, snr 10-11.5
dB** (excellent).

**Junction mesh rules:**
- Reply by **broadcast** (`^all`), NOT direct-message: recent firmware PKI-encrypts
  DMs and drops them `NO_CHANNEL`. The frame is already sealed (AEAD + badge sig), so
  broadcasting leaks nothing.
- Payload on `PRIVATE_APP (256)` is a **complete I3 message** (the bridge already
  `pack_message()`'d it). The junction relays it to the badge AS-IS (leading `0x00`
  flush), does not re-wrap, and sends the badge's reply back on `PRIVATE_APP`.
- One nugget = one COM port, **exclusive**. Don't run `mesh_setup.py`/`mesh_hear.py`
  against a port the junction/dashboard already holds (PermissionError 13).

## 9. Serial-port + shell gotchas (cost us hours)

- **Reflash:** `AUTH` → `BOOTLOADER` before upload, or you get `No serial data
  received`.
- **Residual binary state** between runs: an aborted exchange leaves CRC bytes in
  the badge's line buffer → next command becomes `Unknown command '\xfb\xac ...'`.
  `enter_binary` sends `0x00` + a newline + drains before the command to clear it.
- **Launch long processes in the background** and read their output from files; the
  shell here echoes/dedups commands and often returns exit -1 even on success.
- `pio run -t upload` with `&` from the wrong cwd silently targets the repo root and
  fails (`Not a PlatformIO project`). Always set cwd to `badge-fw/cdc-badge-os`.

## 10. Known-good quick checks

```
# badge alive + module up (over USB)
#   AUTH 123456 ; MODULE LIST  -> mod_lastword [ON] ; TR01 SLOTS -> 28/29/30 Used
# read the 3 role pubkeys
.venv/bin/python badge-fw/tools/badge_serial_test.py --port /dev/ttyACM0 hello
# full hardware signature (needs a human: Y -> 123456 -> Y)
.venv/bin/python badge-fw/tools/badge_serial_test.py --port /dev/ttyACM0 --role daf sign
# junction against the real badge (needs wanbl/badge-fw merged for serial)
JUNCTION_APPROVE_S=120 python junction/mesh_junction.py --dev /dev/ttyACM1 --badge serial:/dev/ttyACM0
```

## 11. Open items / honest limits
- Full REQUEST over the mesh not yet seen (needs §7 — a real invoice + the 3 fixes).
- Only the DAF role was signed on hardware; STOCK attestation + REFUSED (N) + replay/
  tamper rejection not yet exercised on the chip (all pass in the host parity test).
- Two `SerialBadge` versions exist (ours self-contained, collaborator's reuses the
  tools) — reconcile after merging badge-fw (keep his, add our probe-first).
- The approval screen is an `InfoView` + `PinEntryView` (functional). A polished,
  branded screen is a nice-to-have, not required.
