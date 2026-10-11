"""Badge transports: tcp (badge-sim), serial (badge in direct USB), mesh (Meshtastic).

All speak I3: send a COBS-framed message, read a COBS-framed reply (ends with 0x00).
The transport only moves bytes; it never reads or forges the sealed I2 frame inside.
"""
from __future__ import annotations

import os
import socket
import time

from lastword_proto import pack_message, unpack_message, Command


class TransportError(Exception):
    pass


def _read_cobs(recv_byte) -> bytes:
    buf = bytearray()
    while True:
        b = recv_byte()
        if not b:
            raise TransportError("connection closed before frame delimiter")
        buf += b
        if b == b"\x00":
            return bytes(buf)


class TcpTransport:
    """Talks to badge-sim over TCP."""
    def __init__(self, host: str, port: int, timeout: float = 15.0):
        self.host, self.port, self.timeout = host, port, timeout

    def exchange(self, command: int, data: bytes = b"") -> tuple[int, bytes]:
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as s:
            s.settimeout(self.timeout)
            s.sendall(pack_message(command, data))
            frame = _read_cobs(lambda: s.recv(1))
        return unpack_message(frame)


class SerialTransport:
    """Talks to a badge over a direct USB serial port (pyserial)."""
    def __init__(self, port: str, baud: int = 115200, timeout: float = 15.0):
        import serial  # lazy import
        self._serial = serial
        self.port, self.baud, self.timeout = port, baud, timeout

    def exchange(self, command: int, data: bytes = b"") -> tuple[int, bytes]:
        with self._serial.Serial(self.port, self.baud, timeout=self.timeout) as ser:
            ser.write(pack_message(command, data))
            ser.flush()
            buf = bytearray()
            deadline = time.time() + self.timeout
            while time.time() < deadline:
                b = ser.read(1)
                if not b:
                    continue
                buf += b
                if b == b"\x00":
                    return unpack_message(bytes(buf))
            raise TransportError("serial read timed out")


class MeshTransport:
    """Talks to the badge over Meshtastic (PRIVATE_APP port). Requires the meshtastic lib
    and a T3 node on a serial port. Sends the I3 message as a data payload with wantAck,
    and waits for the reply payload on the same port. (Node 1 side; the HP junction relays
    to the badge over node 3 in the full PoC.)"""
    PRIVATE_APP = 256

    def __init__(self, dev_port: str, dest: str = "^all", timeout: float = 30.0,
                 retries: int = 3):
        self.dev_port, self.dest, self.timeout, self.retries = dev_port, dest, timeout, retries

    def exchange(self, command: int, data: bytes = b"") -> tuple[int, bytes]:
        import meshtastic.serial_interface  # lazy import
        from pubsub import pub
        iface = meshtastic.serial_interface.SerialInterface(devPath=self.dev_port)
        reply = {"frame": None}
        # Replies are broadcast on the shared channel, so other I3 traffic shows up too
        # (requests, late replies to someone else's HELLO). Keep only the answer to THIS
        # command: its 0x80 counterpart, or REFUSED.
        expected = {command | 0x80, 0x84}

        def on_receive(packet, interface):
            dec = packet.get("decoded", {})
            if dec.get("portnum") == "PRIVATE_APP" or dec.get("portnum") == self.PRIVATE_APP:
                payload = dec.get("payload")
                if payload and reply["frame"] is None:
                    try:
                        if unpack_message(bytes(payload))[0] in expected:
                            reply["frame"] = payload
                    except Exception:
                        pass  # not an I3 message

        pub.subscribe(on_receive, "meshtastic.receive")
        try:
            msg = pack_message(command, data)
            # a REQUEST waits for a human on the badge (review screen, PIN, confirm):
            # the junction gives the badge 120 s, plus slack for the radio round-trip
            wait = (float(os.environ.get("BRIDGE_MESH_APPROVE_S", "135"))
                    if command == Command.REQUEST else self.timeout)
            deadline = time.time() + wait
            iface.sendData(msg, destinationId=self.dest, portNum=self.PRIVATE_APP,
                           wantAck=True)
            while time.time() < deadline and reply["frame"] is None:
                time.sleep(0.2)
            if reply["frame"] is None:
                raise TransportError(
                    f"frame sent from {self.dev_port} but no reply over the mesh — is "
                    "junction/mesh_junction.py running on the HP (nugget-3, same channel)?")
            return unpack_message(reply["frame"])
        finally:
            iface.close()


def resolve_mesh_port(port: str) -> str:
    """'auto' (or empty) -> the Dell nugget's current COM port. COM numbers change on
    every replug, so match by USB serial (LW_DELL_NUGGET_SERIAL, default nugget-1),
    falling back to the only CH34x (VID 1A86) port present."""
    if port and port.lower() != "auto":
        return port
    import os
    from serial.tools import list_ports
    want = os.environ.get("LW_DELL_NUGGET_SERIAL", "5A5B009671").upper()
    ports = [p for p in list_ports.comports() if p.vid == 0x1A86]
    for p in ports:
        if (p.serial_number or "").upper() == want:
            return p.device
    if len(ports) == 1:
        return ports[0].device
    raise TransportError(
        f"no Dell nugget found (serial {want}); CH34x ports present: "
        + (", ".join(f"{p.device}={p.serial_number}" for p in ports) or "none"))


def make_transport(spec: str):
    """spec: 'tcp:host:port' | 'serial:COMx[:baud]' | 'mesh:COMx' | 'mesh:auto'."""
    kind, _, rest = spec.partition(":")
    if kind == "tcp":
        host, port = rest.split(":")
        return TcpTransport(host, int(port))
    if kind == "serial":
        parts = rest.split(":")
        port = parts[0]
        baud = int(parts[1]) if len(parts) > 1 else 115200
        return SerialTransport(port, baud)
    if kind == "mesh":
        return MeshTransport(resolve_mesh_port(rest))
    raise ValueError(f"unknown transport: {spec}")
