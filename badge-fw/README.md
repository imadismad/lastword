# badge-fw — real hardware badge firmware

This is the real CDC-badge firmware that replaces `badge-sim/`. It makes the
TROPIC01-backed badge speak the exact same I3 protocol as `badge-sim/badge_sim.py`,
byte-for-byte, so the bridge and the contract accept the hardware badge with **no
change** on their side.

## Layout

```
badge-fw/
  cdc-badge-os/        git submodule — upstream firmware (krim404/cdc-badge-os)
  mod_lastword/        our module, kept OUTSIDE the submodule so upstream stays clean
    include/mod_lastword/   LastWordModule.h, BadgeProtocol.h, wire.h, crypto.h
    src/                    BadgeProtocol.cpp, TropicBackend.cpp, wire.cpp,
                            crypto_mbedtls.cpp, LastWordModule.cpp
    test/                   host parity test (no ESP-IDF, no hardware needed)
```

**Design:** the protocol engine (`BadgeProtocol`) is pure — no hardware, no I/O. It
mirrors `badge_sim.py`. All hardware lives in `TropicBackend` (TROPIC01 via the
firmware's `ISecureElement`, e-paper, keypad), behind `IBadgeBackend`. That split
is what lets the **host parity test** replay `proto/vectors.json` through the exact
same engine before anything is flashed.

## What we flash, and what we never touch

- We flash **the ESP32-S3** (the microcontroller), over USB-C, with PlatformIO.
- We **never** flash the TROPIC01, never write its I-Config (irreversible), never
  touch a pairing-key slot. We only ask the chip to *generate* P-256 keys in our
  own ECC slots, *read* their public keys, and *sign* a 32-byte digest.

## Getting the submodule

```
git submodule update --init --recursive badge-fw/cdc-badge-os
```

## Wiring mod_lastword into cdc-badge-os (the fork patch)

`mod_lastword` lives outside the submodule, so building it in needs four small,
reviewable edits inside `badge-fw/cdc-badge-os/`. They are captured as a git patch
so upstream pulls stay clean — never commit them into the submodule.

```
badge-fw/patches/
  lastword.patch   the 4-file diff (CMakeLists.txt, main/CMakeLists.txt,
                   main/module_defaults.h, main/tropic_slot_map.h)
  apply.sh         apply / re-check / --revert, idempotent
```

Apply it to the submodule working tree before building:

```
badge-fw/patches/apply.sh            # apply (safe to re-run)
badge-fw/patches/apply.sh --revert   # undo, leaving the submodule clean
```

What the patch does:

1. **Registers the component** — adds `set(EXTRA_COMPONENT_DIRS
   ${CMAKE_SOURCE_DIR}/../mod_lastword)` in the top-level `CMakeLists.txt`
   (before `project()`), so the firmware finds `mod_lastword`.
2. **Enables the module** — adds `mod_lastword` to `main/CMakeLists.txt` `MODULES`
   and `X("mod_lastword", true)` in `main/module_defaults.h`.
3. **Reserves ECC slots** — in `main/tropic_slot_map.h`, a new
   `MODULE_ID_MOD_LASTWORD 10`, FIDO2 shrunk to 9–27, LASTWORD given 28–30
   (stock/DAF/duress), and the range added to `TROPIC_ECC_SLOT_MAP`. RMEM is
   unchanged. Safe because the badge is vierge (no FIDO2 credential in 28–30).

### The binary channel (no main.cpp change needed)

`mod_lastword` reads binary COBS frames, not the text console. Rather than patch
the main loop, it uses cdc-badge-os's own raw-stream mechanism — the command
registry's **`ByteInterceptor`** (the same one used for raw plugin uploads). While
an interceptor is installed, every received serial byte bypasses line parsing and
goes straight to our handler.

Flow (all in `mod_lastword`, nothing to wire by hand):
1. On `start()`, the module registers a console command `lastword-bin`.
2. The host sends the text line `lastword-bin\n`. The handler installs the byte
   interceptor and the line goes silent (binary from here on).
3. Each byte is fed to the protocol engine; a completed COBS frame (`0x00`) yields
   a reply on the CDC TX.
4. An idle timeout (3 s) removes the interceptor, so a half-sent frame can never
   wedge the console; the text console then resumes normally.

The bridge's `serial:` transport should therefore send `lastword-bin\n` once after
opening the port, before the first `PROVISION`/`REQUEST`. (Add this one line to the
bridge's serial-open path — a small bridge-side change, not a firmware patch.)

Two integration shims in `TropicBackend.cpp` are marked as adapted-in-the-fork and
may need their signatures matched to your exact cdc-badge-os revision:
- `cdc::ui::AppUi::showApprovalScreen(...)` — renders the role banner + fields on
  the e-paper and returns the entered PIN (with a permanent "SOFTWARE KEY" line
  when `softwareKey` is true). Map to the real approval/entry view API.
- `cdc::core::PinManager::verifyRolePin(role, pin)` / `verifyDuressPin(pin)` — map
  to the real PIN API. The duress PIN must resolve to the duress key while keeping
  the DAF role, so the response frame is indistinguishable from a normal approval.

## Host parity test (run this BEFORE flashing)

Proves the C++ engine is byte-compatible with proto/badge-sim. No ESP-IDF, no
hardware — just a host compiler + mbedTLS (`libmbedtls-dev`):

```
cmake -S badge-fw/mod_lastword/test -B build/badge-parity
cmake --build build/badge-parity
./build/badge-parity/parity_test            # run from repo root
```

Note: it reads a few extra fields (`request_frame`, `*_priv`, `gateway_pub`,
`daf_pub`, `contract_addr`, `frame_key`) from `proto/vectors.json`. If your
`vectors.json` predates them, regenerate it (`proto/.../gen_vectors.py`); the test
skips the end-to-end case and still checks CRC/COBS/intent/digest otherwise.

## Flashing (your side — badge over USB-C)

1. **Back up the whole flash first** (16 MB, N16R8). Never `erase_flash`:
   ```
   esptool.py --chip esp32s3 --port <PORT> read_flash 0 0x1000000 badge1_backup.bin
   ```
2. Build + flash with PlatformIO (ESP-IDF). From `badge-fw/cdc-badge-os/`:
   ```
   pio run -t upload
   ```
3. First boot generates the 3 role keys in-chip (slots 28/29/30). `mod_lastword`
   refuses to overwrite an occupied slot, so a vierge badge is required (yours is).
4. Validate the §17 hypotheses on the real chip: the badge signs a P-256 digest
   that a software verifier (and the contract) accept, pubkeys are readable, PINs
   (incl. duress) work. The parity test is the host-side oracle; the on-device
   check is the bridge in `serial:` transport (`PROVISION` then a `REQUEST`).

## Fallback

If the TROPIC01 cannot sign in time, `TropicBackend` falls back to a software P-256
key inside the ESP32 behind the same interface, and the e-paper shows a permanent
"SOFTWARE KEY" banner. The hardware guarantee is then not demonstrated — state it
openly (as the cahier des charges requires).
