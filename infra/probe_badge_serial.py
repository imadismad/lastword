"""Probe whether the device on a serial port speaks the LASTWORD badge I3 protocol.

Sends a COBS-framed HELLO and waits for HELLO_OK(192 bytes = 3 pubkeys). Non-destructive:
HELLO only reads the badge's public keys, it changes nothing.

    python infra/probe_badge_serial.py [PORT] [BAUD]
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "proto", "src"))
sys.path.insert(0, os.path.join(ROOT, "bridge", "src"))

import serial  # noqa: E402
from lastword_proto import pack_message, unpack_message, Command  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM6"
BAUD = int(sys.argv[2]) if len(sys.argv) > 2 else 115200


def main():
    try:
        ser = serial.Serial(PORT, BAUD, timeout=1)
    except Exception as e:
        print(f"OPEN_FAIL {PORT}: {e}")
        return 1
    print(f"OPEN_OK {PORT} @ {BAUD}; sending LASTWORD HELLO...")
    msg = pack_message(Command.HELLO)
    print(f"  tx {len(msg)}B: {msg.hex()}")
    ser.reset_input_buffer()
    ser.write(msg)
    ser.flush()

    buf = bytearray()
    deadline = time.time() + 4
    while time.time() < deadline:
        b = ser.read(1)
        if not b:
            continue
        buf += b
        if b == b"\x00":
            break
    ser.close()

    if not buf:
        print("  NO REPLY -> device does not speak the LASTWORD badge protocol here")
        print("  (likely Meshtastic firmware or something else; not badge-fw)")
        return 2
    print(f"  rx {len(buf)}B: {bytes(buf)[:64].hex()}")
    try:
        cmd, data = unpack_message(bytes(buf))
    except Exception as e:
        print(f"  reply not a valid I3 frame: {e}")
        return 3
    if cmd == Command.HELLO_OK and len(data) == 192:
        print("  HELLO_OK -> this IS a LASTWORD badge! pubkeys:")
        print(f"    stock  = {data[:64].hex()}")
        print(f"    daf    = {data[64:128].hex()}")
        print(f"    duress = {data[128:].hex()}")
        return 0
    print(f"  unexpected reply: cmd=0x{cmd:02x} len={len(data)}")
    return 4


if __name__ == "__main__":
    sys.exit(main())
