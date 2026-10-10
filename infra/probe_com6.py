"""Non-destructive probe of the LoRa nugget: enumerate ports, show USB identity, and try
to open the target port at a few baud rates. Does NOT write badge/mesh frames.

    python infra/probe_com6.py [PORT] [BAUD]
With no args it inspects every COM port's identity, then tries COM6.
"""
import sys
import time

import serial
import serial.tools.list_ports as lp


def enumerate_ports():
    print("=== ENUMERATED PORTS (identity) ===")
    ports = list(lp.comports())
    if not ports:
        print("  (none)")
    for p in ports:
        print(f"  {p.device:6}  {p.description}")
        print(f"          hwid={p.hwid}")
        if p.vid is not None:
            print(f"          VID:PID={p.vid:04X}:{p.pid:04X}  "
                  f"serial={p.serial_number}  mfg={p.manufacturer}")
    return [p.device for p in ports]


def try_open(port: str, baud: int) -> bool:
    try:
        ser = serial.Serial(port, baud, timeout=1)
    except Exception as e:
        print(f"  OPEN_FAIL {port} @ {baud}: {e}")
        return False
    print(f"  OPEN_OK {port} @ {baud}")
    try:
        ser.reset_input_buffer()
        ser.write(b"\r\n")
        ser.flush()
    except Exception as e:
        print(f"    write_warn: {e}")
    deadline = time.time() + 2.5
    raw = bytearray()
    while time.time() < deadline:
        chunk = ser.read(256)
        if chunk:
            raw += chunk
    ser.close()
    print(f"    bytes_read={len(raw)}")
    if raw:
        printable = bytes(b if 32 <= b < 127 or b in (10, 13) else 46 for b in raw[:300])
        print("    ascii:", printable.decode("ascii", "replace"))
        print("    hex  :", raw[:48].hex())
    else:
        print("    (silent: no spontaneous output)")
    return True


def main():
    if len(sys.argv) > 1:
        port = sys.argv[1]
        baud = int(sys.argv[2]) if len(sys.argv) > 2 else 115200
        enumerate_ports()
        print(f"=== TRY {port} ===")
        try_open(port, baud)
        return

    enumerate_ports()
    print("=== TRY COM6 at common baud rates ===")
    for b in (115200, 9600, 921600):
        if try_open("COM6", b):
            break


if __name__ == "__main__":
    main()
