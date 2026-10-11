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
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "proto", "src"))
sys.path.insert(0, os.path.join(ROOT, "badge-sim"))

PRIVATE_APP = 256


def _is_reply(frame: bytes) -> bool:
    """I3 replies (HELLO_OK, PROV_OK, RESPONSE, REFUSED) have the 0x80 bit set; replies
    are broadcast, so the junction hears them too and must not feed them to the badge."""
    from lastword_proto import unpack_message
    try:
        return bool(unpack_message(frame)[0] & 0x80)
    except Exception:
        return True  # not an I3 message at all


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
    """Relay to a REAL badge chip over USB serial (badge-fw).

    Reuses badge-fw/tools/badge_serial_test.py (validated on hardware) for the console
    bring-up: probe-first, then secure-serial AUTH + 'lastword-bin' only if the byte
    interceptor is not already armed, and a frame reader that skips the firmware's
    interleaved log lines. The port stays open across frames (PROVISION, then the STOCK
    and DAF REQUESTs arrive as separate mesh packets): we enter binary mode once and
    re-arm only after a failure. A REQUEST answers only after the human approves on the
    keypad (Y -> PIN -> Y), so it gets a long timeout."""
    def __init__(self, port: str, baud: int = 115200):
        import serial
        sys.path.insert(0, os.path.join(ROOT, "badge-fw", "tools"))
        try:
            import badge_serial_test as bst
        except ImportError as e:
            raise SystemExit(f"--badge serial needs badge-fw/tools/badge_serial_test.py: {e}")
        self._serial, self._bst = serial, bst
        self.port, self.baud = port, baud
        self._ser = None
        self._armed = False  # True once the byte interceptor is installed
        self.label = f"serial:{port}@{baud} (hardware badge)"

    def handle(self, framed: bytes) -> bytes:
        from lastword_proto import Command, unpack_message
        cmd = unpack_message(framed)[0]
        try:
            if self._ser is None or not self._ser.is_open:
                self._ser = self._serial.Serial(self.port, self.baud, timeout=0.5)
                self._armed = False  # a fresh port starts on the text console
            if not self._armed:
                self._bst.enter_binary(self._ser)
                self._armed = True
            self._ser.reset_input_buffer()
            self._ser.write(b"\x00" + framed)  # leading 0x00 flushes residual state
            self._ser.flush()
            if cmd == Command.REQUEST:
                print("[junction] REQUEST on the badge: review the screen, press Y, "
                      "enter the PIN, press Y")
                timeout = float(os.environ.get("JUNCTION_APPROVE_S", "120"))
            else:
                timeout = 15.0
            return self._bst.read_cobs_frame(self._ser, timeout=timeout)
        except Exception:
            # lost sync / timeout: drop the port and the armed state so the next frame
            # reopens and re-arms from a known state
            self._armed = False
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None
            raise


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

    badge_lock = threading.Lock()  # one exchange at a time on the badge

    def on_receive(packet, interface):
        dec = packet.get("decoded", {})
        pn = dec.get("portnum")
        if pn not in ("PRIVATE_APP", PRIVATE_APP):
            return
        payload = dec.get("payload")
        if not payload:
            return
        src = packet.get("fromId") or packet.get("from")
        if _is_reply(bytes(payload)):
            return  # our own (or another junction's) broadcast reply, not a request
        print(f"[junction] <- {len(payload)}B frame from {src}; asking badge ...")
        # the badge may wait minutes for a human: never block the radio's RX thread
        threading.Thread(target=_serve, args=(bytes(payload), src, interface),
                         daemon=True).start()

    def _serve(frame: bytes, src, interface):
        try:
            with badge_lock:
                resp = badge.handle(frame)
        except Exception as e:
            print(f"[junction] badge error: {e}")
            return
        # reply on the shared channel (broadcast), like the bridge sends. A direct message
        # to `src` gets PKI-encrypted by recent firmware and is dropped with NO_CHANNEL
        # when the two nuggets don't share each other's public key; the frame itself is
        # already sealed (I2 AEAD + badge signature), so broadcasting it leaks nothing.
        try:
            interface.sendData(resp, destinationId="^all", portNum=PRIVATE_APP, wantAck=True)
            print(f"[junction] -> {len(resp)}B response (broadcast, for {src})")
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
