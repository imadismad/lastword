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
from lastword_proto import (
    pack_message, unpack_message, Command, RefuseReason,
    Intent, Role, digest, build_request_frame, open_frame, parse_response_body,
    pub_from_bytes, verify_digest,
)
from lastword_proto.crypto import sig_from_bytes, is_low_s

# the bridge's gateway key (same seed as badge-sim) so the real badge verifies us
sys.path.insert(0, os.path.join(_REPO, "bridge", "src"))
from lastword_bridge.gatewaykey import GatewayKey


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


def probe_binary(ser: serial.Serial, timeout: float = 8.0) -> bool:
    """True if the badge is ALREADY in binary mode (interceptor armed): send a HELLO
    and see whether a valid I3 reply comes back. The interceptor stays armed ~120 s
    after a session, so a fresh process can inherit it; probing first avoids sending
    AUTH text that an armed interceptor would swallow as binary (the 'got 8B' desync)."""
    ser.reset_input_buffer()
    ser.write(b"\x00" + pack_message(Command.HELLO))
    ser.flush()
    try:
        read_cobs_frame(ser, timeout=timeout)
        return True
    except TimeoutError:
        return False


def enter_binary(ser: serial.Serial):
    """Put the console into a known-clean text state, then install the byte
    interceptor with the 'lastword-bin' command.

    Residual-state guard: a previous (aborted) binary exchange can leave bytes in
    the firmware's line buffer that get prepended to our next command ("Unknown
    command '\\xfb\\xac lastword-bin'"), OR leave the byte interceptor still armed.
    We clear BOTH: send 0x00 (ends any binary frame / lets an armed interceptor
    time out), then several newlines (flush any partial text line), drain, and only
    then send the command — retrying a couple of times if needed."""
    # Secure serial is enabled on this build: EVERY command except PING/AUTH needs
    # a prior AUTH (confirmed by the badge replying "Not authenticated" to
    # lastword-bin, and by the cdc-badge-os serial-console docs). The session
    # times out after 5 min idle, so authenticate at the start of every exchange —
    # unless the interceptor is still armed, in which case AUTH must NOT be sent.
    if probe_binary(ser):
        return
    ser.reset_input_buffer()
    # 0x00 closes any residual binary frame; newline flushes a partial text line
    ser.write(b"\x00\n")
    ser.flush()
    _drain(ser, 0.4)
    ser.write(b"AUTH 123456\n")
    ser.flush()
    time.sleep(0.6)
    _drain(ser, 0.3)

    for attempt in range(3):
        ser.reset_input_buffer()
        ser.write(b"\n\n")
        ser.flush()
        _drain(ser, 0.4)

        ser.reset_input_buffer()
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
        if b"Executing: lastword-bin" in seen and b"Unknown command" not in seen:
            time.sleep(0.1)
            ser.reset_input_buffer()
            return
        # it may have armed in between, or an old interceptor is still up
        if probe_binary(ser):
            return
        # dirty: wait out any armed interceptor idle-timeout (3 s) and retry
        time.sleep(3.2)
    raise RuntimeError("could not enter binary mode cleanly: " + repr(bytes(seen[-120:])))


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


# Demo chain params (match proto/vectors + the local L1). Overridable via CLI.
DEFAULT_CHAIN_ID = 99999            # infra/genesis.json chainId
DEFAULT_CONTRACT = bytes(20)        # 0x000..0 placeholder for the signature test


def do_provision(ser: serial.Serial, frame_key: bytes, chain_id: int,
                 contract_addr: bytes, gateway_pub: bytes):
    assert len(frame_key) == 32 and len(contract_addr) == 20 and len(gateway_pub) == 64
    payload = frame_key + chain_id.to_bytes(8, "big") + contract_addr + gateway_pub
    rcmd, data = exchange(ser, Command.PROVISION, payload)
    if rcmd != Command.PROV_OK:
        reason = data[0] if (rcmd == Command.REFUSED and data) else None
        raise RuntimeError(f"PROVISION failed: cmd 0x{rcmd:02x}"
                           + (f" reason 0x{reason:02x}" if reason is not None else ""))


def do_request(ser: serial.Serial, frame_key: bytes, chain_id: int,
               contract_addr: bytes, gateway: "GatewayKey", intent: "Intent",
               badge_id: int, counter: int, approve_timeout: float = 90.0):
    """Send a REQUEST and wait for the human to approve on the badge keypad.

    Builds the I2 request frame (intent + gateway sig over the digest), sends it,
    then waits up to approve_timeout for the deferred RESPONSE/REFUSED that the
    badge emits AFTER you press Y, type the PIN, and press Y again on the device."""
    dg = digest(intent, chain_id, contract_addr)
    gw_sig = gateway.sign(dg)
    frame = build_request_frame(frame_key, badge_id, counter, intent.encode(), gw_sig)
    # send REQUEST, then wait a long time for the human approval reply
    ser.write(b"\x00" + pack_message(Command.REQUEST, frame))
    ser.flush()
    print("  >> REQUEST sent. On the badge: review the screen, press Y, "
          "enter PIN 123456, press Y.")
    rframe = read_cobs_frame(ser, timeout=approve_timeout)
    rcmd, data = unpack_message(rframe)
    if rcmd == Command.REFUSED:
        reason = data[0] if data else 0xFF
        raise RuntimeError(f"badge REFUSED request: reason 0x{reason:02x}")
    if rcmd != Command.RESPONSE:
        raise RuntimeError(f"unexpected reply cmd 0x{rcmd:02x}")
    hdr, pt = open_frame(frame_key, data)
    reqId, decision, badge_sig = parse_response_body(pt)
    return {"reqId": reqId, "decision": decision, "badge_sig": badge_sig.hex(), "digest": dg.hex()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--role", choices=["stock", "daf"], default="daf",
                    help="which role the sign test requests")
    ap.add_argument("--chain-id", type=int, default=DEFAULT_CHAIN_ID)
    ap.add_argument("cmd", choices=["hello", "pubkeys", "sign"])
    args = ap.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=0.5)
    time.sleep(0.3)
    try:
        if args.cmd in ("hello", "pubkeys"):
            keys = do_hello(ser)
            print(json.dumps(keys, indent=2))
            return

        # sign: HELLO (get role pubkeys) -> PROVISION -> REQUEST -> verify signature
        keys = do_hello(ser)
        role_pub = bytes.fromhex(keys[args.role])

        frame_key = bytes(range(32))          # demo frame key (same both sides)
        contract_addr = DEFAULT_CONTRACT
        gateway = GatewayKey.from_seed()      # matches badge's expected gateway key

        do_provision(ser, frame_key, args.chain_id, contract_addr, gateway.public_bytes())
        print("  provisioned OK (frameKey, chainId, contract, gatewayPub)")

        role = Role.DAF if args.role == "daf" else Role.STOCK
        intent = Intent(
            reqId=4242, beneficiary=bytes.fromhex("00112233445566778899aabbccddeeff00112233"),
            token=0, amount=1500000, nonce=7, deadline=2000000000,
            quoteHash=bytes(range(32)), flags=int(role), policy=1,
        )
        res = do_request(ser, frame_key, args.chain_id, contract_addr, gateway,
                         intent, badge_id=1, counter=5)

        # verify the badge signature against the role pubkey we read at HELLO
        pub = pub_from_bytes(role_pub)
        r, s = sig_from_bytes(bytes.fromhex(res["badge_sig"]))
        ok = verify_digest(pub, bytes.fromhex(res["digest"]), r, s)
        print(json.dumps({
            "reqId": res["reqId"], "decision": res["decision"],
            "signature_valid": ok, "low_s": is_low_s(s), "role": args.role,
        }, indent=2))
        if not ok:
            raise SystemExit("SIGNATURE INVALID")
        print("\n  HARDWARE SIGNATURE OK — the TROPIC01 signed a digest the "
              "verifier accepts.")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
