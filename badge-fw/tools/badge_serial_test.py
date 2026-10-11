#!/usr/bin/env python3
"""badge_serial_test.py — talk to the real badge over USB-CDC (transport 'serial'),
step by step, to validate mod_lastword on hardware before any radio is involved.

It reuses the frozen proto library (lastword_proto) so the frames are byte-identical
to what the bridge and badge-sim use. Flow:
  1. open the port, enter the binary channel with the text line 'lastword-bin\\n',
  2. speak I3 (COBS+CRC messages): HELLO, PROVISION, REQUEST,
  3. read the framed replies and decode them.

Usage (from repo root, with the venv):
  .venv/bin/python badge-fw/tools/badge_serial_test.py --port /dev/ttyACM0 hello
  .venv/bin/python badge-fw/tools/badge_serial_test.py --port /dev/ttyACM0 pubkeys

Subcommands:
  hello     send HELLO, print the 3 role pubkeys (stock/DAF/duress)
  pubkeys   alias for hello, emits JSON suitable for the contract deploy

This script does NOT need the bridge; it is a minimal, dependency-light harness to
prove the serial path and the badge signing before wiring the full bridge.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

# make lastword_proto importable from the monorepo without installing
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO, "proto", "src"))

import serial  # pyserial
from lastword_proto import pack_message, unpack_message, Command, RefuseReason


ENTER_BINARY_LINE = b"lastword-bin\n"


from lastword_proto import cobs_decode, crc16_ccitt


def _looks_like_valid_frame(cobs_payload: bytes) -> bool:
    """True if cobs_payload (without the 0x00) COBS-decodes to a CRC-valid I3 msg."""
    try:
        raw = cobs_decode(cobs_payload)
    except Exception:
        return False
    if len(raw) < 5:
        return False
    length = int.from_bytes(raw[1:3], "big")
    if 3 + length + 2 > len(raw):
        return False
    crc_recv = int.from_bytes(raw[3 + length:3 + length + 2], "big")
    return crc_recv == crc16_ccitt(raw[:3 + length])


def read_cobs_frame(ser: serial.Serial, timeout: float = 6.0) -> bytes:
    """Read the badge reply, tolerating interleaved text log lines.

    The firmware emits INFO logs (e.g. '[I][TR01] ...\\n') on the same CDC line as
    the binary reply, because reading the role pubkeys opens/closes TROPIC01
    sessions. So we cannot assume the first 0x00 ends our frame. Strategy: collect
    bytes for up to `timeout`, splitting on 0x00 delimiters, and return the FIRST
    0x00-terminated chunk that COBS-decodes to a CRC-valid I3 message. Everything
    else (log text) is ignored."""
    deadline = time.time() + timeout
    buf = bytearray()
    while time.time() < deadline:
        b = ser.read(256)
        if b:
            buf += b
        # A full I3 reply ends on a 0x00. Only attempt extraction once we have at
        # least one 0x00 (and keep reading in case more arrives). The reply can
        # take several seconds (reading 3 pubkeys opens/closes TROPIC01 sessions,
        # which emit slow INFO logs on the same line before the frame).
        if 0x00 not in buf:
            continue
        frame = _extract_frame(bytes(buf))
        if frame is not None:
            return frame
    # last attempt on whatever we have
    frame = _extract_frame(bytes(buf))
    if frame is not None:
        return frame
    raise TimeoutError("no valid I3 frame received before timeout "
                       f"(got {len(buf)} bytes)")


def _extract_frame(buf: bytes):
    """Find the first COBS+CRC-valid I3 frame inside buf (which may contain
    interleaved log text before/after). Returns the frame incl. its 0x00, or None."""
    start = 0
    n = len(buf)
    while start < n:
        z = buf.find(0x00, start)
        if z < 0:
            break
        # try every possible frame start within [start, z)
        for s in range(start, z):
            cand = buf[s:z]
            if cand and _looks_like_valid_frame(cand):
                return cand + b"\x00"
        start = z + 1
    return None


def _drain(ser: serial.Serial, settle: float = 0.4):
    """Read and discard everything the badge has pending until it goes quiet."""
    end = time.time() + settle
    while time.time() < end:
        d = ser.read(256)
        if d:
            end = time.time() + settle  # keep draining while bytes flow


def enter_binary(ser: serial.Serial):
    """Put the console into a known-clean text state, then install the byte
    interceptor with the 'lastword-bin' command.

    Residual-state guard: a previous (aborted) binary exchange can leave CRC/frame
    bytes in the firmware's line buffer, which then get prepended to our next
    command ("Unknown command '\\xfb\\xac lastword-bin'"). To clear it we first send
    a lone newline (flushes any partial line), drain, THEN send the command."""
    # 1. flush any partial line left in the firmware's command buffer
    ser.reset_input_buffer()
    ser.write(b"\n")
    ser.flush()
    _drain(ser, 0.3)
    # 2. now send the real command and wait for the post-command prompt
    ser.write(ENTER_BINARY_LINE)
    ser.flush()
    deadline = time.time() + 1.5
    seen = bytearray()
    while time.time() < deadline:
        d = ser.read(256)
        if d:
            seen += d
            if b"Executing: lastword-bin" in seen and seen.rstrip().endswith(b">"):
                break
    if b"Unknown command" in seen:
        raise RuntimeError("badge did not accept 'lastword-bin' (dirty line state): "
                           + repr(bytes(seen[-120:])))
    time.sleep(0.1)
    ser.reset_input_buffer()


def exchange(ser: serial.Serial, cmd: int, data: bytes = b"") -> tuple[int, bytes]:
    """Send one I3 message and read one framed reply.

    A leading 0x00 flush byte is prepended: entering binary mode can leave a stray
    byte (e.g. the line terminator) in the badge's COBS reassembly buffer. A lone
    0x00 makes the badge's feedByte() decode-and-discard whatever preceded it,
    leaving a clean buffer for our real frame. Harmless if the buffer was already
    empty."""
    ser.write(b"\x00" + pack_message(cmd, data))
    ser.flush()
    # HELLO can take a few seconds: it reads 3 pubkeys, each opening/closing a
    # TROPIC01 session, so allow generous time.
    frame = read_cobs_frame(ser, timeout=10.0)
    return unpack_message(frame)


def do_hello(ser: serial.Serial) -> dict:
    enter_binary(ser)
    rcmd, data = exchange(ser, Command.HELLO)
    if rcmd == Command.REFUSED:
        reason = data[0] if data else 0xFF
        raise RuntimeError(f"badge REFUSED hello: reason 0x{reason:02x}")
    if rcmd != Command.HELLO_OK:
        raise RuntimeError(f"unexpected reply cmd 0x{rcmd:02x}")
    if len(data) != 192:
        raise RuntimeError(f"HELLO_OK must carry 3x64 pubkeys (192 B), got {len(data)}")
    return {
        "stock":  data[0:64].hex(),
        "daf":    data[64:128].hex(),
        "duress": data[128:192].hex(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("cmd", choices=["hello", "pubkeys"])
    args = ap.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=0.5)
    time.sleep(0.3)
    try:
        keys = do_hello(ser)
    finally:
        ser.close()

    if args.cmd in ("hello", "pubkeys"):
        print(json.dumps(keys, indent=2))


if __name__ == "__main__":
    main()
