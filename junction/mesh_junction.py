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
    """Relay to a REAL badge chip over USB serial (badge-fw).

    The badge-fw console is NOT a dumb pass-through — it needs the exact bring-up
    the serial harness proved (badge-fw/tools/badge_serial_test.py):
      * secure serial is ON: authenticate (AUTH <pin>) before any command;
      * enter the binary I3 channel with the text line 'lastword-bin' (bare LF —
        CRLF makes the badge execute on \\r and swallow \\n as a stray binary byte);
      * the payload coming off the mesh is ALREADY a complete I3 message (the bridge
        pack_message()'d it), so send it as-is with a leading 0x00 flush — do NOT
        re-wrap it;
      * the reply is interleaved with slow '[I][TR01] ...' logs and, for a REQUEST,
        only arrives AFTER the human reads the e-paper and types the PIN on the
        keypad. So read tolerantly and wait a long time.
    The port is kept open across frames (PROVISION, then the stock + DAF REQUESTs
    each arrive as separate mesh packets); we authenticate + enter binary once and
    re-arm lazily if the session/interceptor dropped.
    """

    PIN = os.environ.get("LW_BADGE_PIN", "123456")

    def __init__(self, port: str, baud: int = 115200):
        import serial
        self._serial = serial
        self.port, self.baud = port, baud
        self.label = f"serial:{port}@{baud} (hardware badge)"
        self._ser = None
        self._armed = False   # True once the byte interceptor is installed
        # frozen proto codec: validate reply frames and tolerate interleaved logs
        from lastword_proto import cobs_decode, crc16_ccitt
        self._cobs_decode = cobs_decode
        self._crc16 = crc16_ccitt

    def _open(self):
        if self._ser is None or not self._ser.is_open:
            self._ser = self._serial.Serial(self.port, self.baud, timeout=0.4)
            time.sleep(0.3)
            self._armed = False  # a fresh port is back on the text console

    def _drain(self, settle=0.4):
        end = time.time() + settle
        while time.time() < end:
            if self._ser.read(256):
                end = time.time() + settle

    def _probe_binary(self) -> bool:
        """Return True if the badge is ALREADY in binary mode (interceptor armed):
        send a HELLO and see if a valid I3 reply comes back. The interceptor stays
        armed ~120 s between sessions, so a fresh process can inherit it; probing
        avoids sending AUTH text that an armed interceptor would swallow as binary."""
        from lastword_proto import pack_message, Command
        s = self._ser
        s.reset_input_buffer()
        s.write(b"\x00" + pack_message(Command.HELLO))
        s.flush()
        try:
            self._read_reply(timeout=8.0)
            return True
        except Exception:
            return False

    def _enter_binary(self):
        """Ensure the badge is in the binary I3 channel.

        Robust to any prior state: first PROBE (the interceptor may still be armed
        from an earlier session; re-AUTHing then would be swallowed). Only if the
        probe fails do we run AUTH + 'lastword-bin'. Bare-LF terminators throughout
        (CRLF makes the badge execute on \\r and eat \\n as a stray binary byte)."""
        s = self._ser
        if self._probe_binary():
            return  # already armed — good to go
        # not armed: do the full bring-up
        s.reset_input_buffer()
        s.write(b"\x00\n")          # close any residual binary frame / partial line
        s.flush()
        self._drain(0.4)
        s.write(f"AUTH {self.PIN}\n".encode())
        s.flush()
        time.sleep(0.6)
        self._drain(0.3)
        for _ in range(3):
            s.reset_input_buffer()
            s.write(b"\n\n")
            s.flush()
            self._drain(0.4)
            s.reset_input_buffer()
            s.write(b"lastword-bin\n")
            s.flush()
            deadline = time.time() + 1.5
            seen = bytearray()
            while time.time() < deadline:
                d = s.read(256)
                if d:
                    seen += d
                    if b"Executing: lastword-bin" in seen and seen.rstrip().endswith(b">"):
                        break
            if b"Executing: lastword-bin" in seen and b"Unknown command" not in seen:
                s.reset_input_buffer()
                return
            # Maybe it armed between probe and now, or an old interceptor is still
            # up: re-probe before giving up / waiting out the idle timeout.
            if self._probe_binary():
                return
            time.sleep(3.2)         # wait out an armed interceptor's idle timeout
        raise RuntimeError("badge did not enter binary mode: " + repr(bytes(seen[-120:])))

    def _valid_frame(self, cobs_payload: bytes) -> bool:
        try:
            raw = self._cobs_decode(cobs_payload)
        except Exception:
            return False
        if len(raw) < 5:
            return False
        length = int.from_bytes(raw[1:3], "big")
        if 3 + length + 2 > len(raw):
            return False
        crc = int.from_bytes(raw[3 + length:3 + length + 2], "big")
        return crc == self._crc16(raw[:3 + length])

    def _read_reply(self, timeout: float) -> bytes:
        """Return the first COBS+CRC-valid I3 reply (incl. its 0x00), ignoring any
        interleaved log text before/after it."""
        s = self._ser
        deadline = time.time() + timeout
        buf = bytearray()
        while time.time() < deadline:
            d = s.read(256)
            if d:
                buf += d
            if 0x00 not in buf:
                continue
            start = 0
            while True:
                try:
                    z = buf.index(0x00, start)
                except ValueError:
                    break
                for st in range(start, z):
                    cand = bytes(buf[st:z])
                    if cand and self._valid_frame(cand):
                        return cand + b"\x00"
                start = z + 1
        raise RuntimeError(f"no valid I3 reply within {timeout:.0f}s (got {len(buf)}B)")

    def handle(self, framed: bytes) -> bytes:
        # `framed` is a complete I3 message from the bridge (PROVISION or REQUEST).
        # REQUEST waits for a human on the badge keypad, so allow a long timeout.
        #
        # The badge's byte interceptor, once installed by 'lastword-bin', stays armed
        # (120 s idle) and keeps forwarding every serial byte straight to the proto
        # engine. So we must enter binary mode EXACTLY ONCE per session and then send
        # raw frames directly — re-sending 'AUTH'/'lastword-bin' while armed would be
        # swallowed as binary and desync the link (the "b''" failure we saw). We keep
        # the port open across frames and only (re)arm when not already armed.
        self._open()
        try:
            if not self._armed:
                self._enter_binary()
                self._armed = True
            self._ser.reset_input_buffer()
            self._ser.write(b"\x00" + framed)   # leading 0x00 flushes residual state
            self._ser.flush()
            # generous: a DAF REQUEST needs the operator to read + PIN on the keypad
            return self._read_reply(timeout=float(os.environ.get("LW_BADGE_TIMEOUT", "120")))
        except Exception:
            # lost sync / timeout: drop the port AND our armed belief so the next
            # frame reopens and re-arms from a known state.
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
