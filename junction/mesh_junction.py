"""HP junction - the mesh->badge relay that runs on the OPERATOR (HP) machine.

This is the real receiving side of the LoRa link. It:
  1. opens its OWN Meshtastic node (node 2) on a serial port,
  2. listens for PRIVATE_APP (256) packets - each payload is a complete I3 frame that the
     bridge (on the Dell, node 1) sent,
  3. hands the frame to a LOCAL BADGE and gets the I3 response:
       - --badge sim           : software badge-sim in-process (clés P-256 logicielles)
       - --badge serial:COMx   : a real badge chip over USB (badge-fw, track N)
       - --badge tcp:host:port : a badge-sim running elsewhere on this machine
  4. sends the response frame back over the mesh to the node it came from.

The junction NEVER forges the sealed I2 frame; it only moves bytes between the radio and
the badge. This makes the radio hop and the Dell<->HP network separation REAL - only the
P-256 chip remains to be swapped in once badge-fw exists.

Run on the HP machine (node 2 plugged in on, e.g., COM5):
    python junction/mesh_junction.py --dev COM5 --badge sim --auto
    python junction/mesh_junction.py --dev COM5 --badge serial:COM6        # real chip
    python junction/mesh_junction.py --dev COM5 --badge tcp:127.0.0.1:8766 # external sim

Requires: pip install meshtastic  (and pyserial, cryptography for the sim badge).
"""
from __future__ import annotations

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "proto", "src"))
sys.path.insert(0, os.path.join(ROOT, "badge-sim"))

PRIVATE_APP = 256


# --------------------------------------------------------------- badge back-ends
class SimBadge:
    """In-process software badge (reuses badge_sim.BadgeSim.handle)."""
    def __init__(self, auto: bool):
        import badge_sim
        self._b = badge_sim.BadgeSim(auto=auto)
        self.label = "sim (software P-256 keys)"

    def handle(self, framed: bytes) -> bytes:
        return self._b.handle(framed)


class TcpBadge:
    """Relay to a badge-sim listening on TCP somewhere on this machine."""
    def __init__(self, host: str, port: int):
        self.host, self.port = host, int(port)
        self.label = f"tcp:{host}:{port}"

    def handle(self, framed: bytes) -> bytes:
        import socket
        with socket.create_connection((self.host, self.port), timeout=15) as s:
            s.sendall(framed)
            buf = bytearray()
            while True:
                ch = s.recv(1)
                if not ch:
                    break
                buf += ch
                if ch == b"\x00":
                    break
            return bytes(buf)


class SerialBadge:
    """Relay to a REAL badge chip over USB serial (badge-fw)."""
    def __init__(self, port: str, baud: int = 115200):
        import serial
        self._serial = serial
        self.port, self.baud = port, baud
        self.label = f"serial:{port}@{baud} (hardware badge)"

    def handle(self, framed: bytes) -> bytes:
        with self._serial.Serial(self.port, self.baud, timeout=15) as ser:
            ser.write(framed)
            ser.flush()
            buf = bytearray()
            deadline = time.time() + 15
            while time.time() < deadline:
                ch = ser.read(1)
                if not ch:
                    continue
                buf += ch
                if ch == b"\x00":
                    break
            return bytes(buf)


def make_badge(spec: str, auto: bool):
    if spec == "sim":
        return SimBadge(auto)
    kind, _, rest = spec.partition(":")
    if kind == "tcp":
        host, port = rest.split(":")
        return TcpBadge(host, port)
    if kind == "serial":
        parts = rest.split(":")
        return SerialBadge(parts[0], int(parts[1]) if len(parts) > 1 else 115200)
    raise ValueError(f"unknown --badge spec: {spec}")


# --------------------------------------------------------------- mesh relay loop
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", required=True, help="serial port of THIS node (e.g. COM5)")
    ap.add_argument("--badge", default="sim", help="sim | serial:COMx | tcp:host:port")
    ap.add_argument("--auto", action="store_true", help="auto-approve (sim badge only)")
    args = ap.parse_args()

    try:
        import meshtastic.serial_interface
        from pubsub import pub
    except Exception as e:
        print(f"meshtastic lib missing: {e}\n  pip install meshtastic")
        return 1

    badge = make_badge(args.badge, args.auto)
    print(f"[junction] badge backend: {badge.label}")
    print(f"[junction] opening node on {args.dev} ...")
    iface = meshtastic.serial_interface.SerialInterface(devPath=args.dev)
    info = iface.getMyNodeInfo() or {}
    me = (info.get("user") or {}).get("id", "?")
    print(f"[junction] node {me} up; relaying PRIVATE_APP({PRIVATE_APP}) <-> badge. Ctrl-C to stop.")

    def on_receive(packet, interface):
        dec = packet.get("decoded", {})
        pn = dec.get("portnum")
        if pn not in ("PRIVATE_APP", PRIVATE_APP):
            return
        payload = dec.get("payload")
        if not payload:
            return
        src = packet.get("fromId") or packet.get("from")
        print(f"[junction] <- {len(payload)}B frame from {src}; asking badge ...")
        try:
            resp = badge.handle(bytes(payload))
        except Exception as e:
            print(f"[junction] badge error: {e}")
            return
        # reply to the sender on the same private port
        try:
            interface.sendData(resp, destinationId=src, portNum=PRIVATE_APP, wantAck=True)
            print(f"[junction] -> {len(resp)}B response to {src}")
        except Exception as e:
            print(f"[junction] send error: {e}")

    pub.subscribe(on_receive, "meshtastic.receive")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[junction] stopping")
    finally:
        iface.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
