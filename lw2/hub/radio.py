"""Gateway radio: one persistent Meshtastic link on nugget-1, owned by the hub alone.

v1 opened the serial node for every frame (5-10 s each, and it fought the dashboard
for the COM port). Here the link stays open: frames go out immediately, every packet
heard is measured (RSSI, SNR, hops) and published, and only an authenticated-shape
LASTWORD reply to the exact command we sent is handed back to the bridge. Anything
else on the channel (text, telemetry, other nodes) is logged as ignored and never
reaches the agent."""
from __future__ import annotations

import threading
import time

from lastword_proto import pack_message, unpack_message, Command

from .airtime import airtime_ms, preset_name
from .events import BUS

PRIVATE_APP = 256
CMD_NAMES = {0x01: "HELLO", 0x81: "HELLO_OK", 0x02: "PROVISION", 0x82: "PROV_OK",
             0x03: "REQUEST", 0x83: "RESPONSE", 0x84: "REFUSED"}


class RadioError(Exception):
    pass


class MeshRadio:
    def __init__(self, port: str, name: str = "gateway"):
        self.port, self.name = port, name
        self.iface = None
        self.node_id = None
        self.preset = 0
        self.region = None
        self.channel_url = None
        self._xlock = threading.Lock()       # one I3 exchange on air at a time
        self._waiter: dict | None = None
        self.stats = {"tx": 0, "rx": 0, "ignored": 0, "airtime_ms": 0.0}
        self.last_rx: dict | None = None

    # ------------------------------------------------------------------ lifecycle
    def open(self) -> None:
        import meshtastic.serial_interface
        from pubsub import pub
        pub.subscribe(self._on_rx, "meshtastic.receive")
        self.iface = meshtastic.serial_interface.SerialInterface(devPath=self.port)
        me = (self.iface.getMyNodeInfo() or {}).get("user", {})
        self.node_id = me.get("id")
        try:
            lc = self.iface.localNode.localConfig.lora
            self.preset, self.region = int(lc.modem_preset), int(lc.region)
            self.channel_url = self.iface.localNode.getURL()
        except Exception:
            pass
        BUS.emit("radio.up", side=self.name, port=self.port, node=self.node_id,
                 preset=preset_name(self.preset), region=self.region)

    def close(self) -> None:
        try:
            if self.iface:
                self.iface.close()
        finally:
            self.iface = None

    @property
    def up(self) -> bool:
        return self.iface is not None

    # ------------------------------------------------------------------ receive path
    def _on_rx(self, packet, interface):
        if interface is not self.iface or packet.get("fromId") == self.node_id:
            return  # other interfaces, or our own node's local telemetry
        dec = packet.get("decoded") or {}
        port = dec.get("portnum")
        hop_start, hop_limit = packet.get("hopStart"), packet.get("hopLimit")
        meta = {
            "side": self.name, "from": packet.get("fromId"), "port": port,
            "rssi": packet.get("rxRssi"), "snr": packet.get("rxSnr"),
            "hops": (hop_start - hop_limit) if hop_start is not None and hop_limit is not None else None,
        }
        if port in ("PRIVATE_APP", PRIVATE_APP) and dec.get("payload"):
            payload = bytes(dec["payload"])
            try:
                cmd, _data = unpack_message(payload)
            except Exception:
                self.stats["ignored"] += 1
                BUS.emit("radio.ignored", reason="not a LASTWORD I3 message", size=len(payload), **meta)
                return
            self.stats["rx"] += 1
            self.last_rx = {**meta, "ts": time.time()}
            BUS.emit("radio.rx", cmd=CMD_NAMES.get(cmd, hex(cmd)), size=len(payload),
                     airtime_ms=round(airtime_ms(len(payload), self.preset)), **meta)
            w = self._waiter
            if w and w["frame"] is None and cmd in w["expected"]:
                w["frame"], w["meta"] = payload, meta
                w["event"].set()
            return
        if port == "TEXT_MESSAGE_APP":
            self.stats["ignored"] += 1
            BUS.emit("radio.ignored", reason="text message: never forwarded to the agent",
                     text=(dec.get("text") or "")[:80], **meta)
        elif port and port not in ("ROUTING_APP",):
            BUS.emit("radio.heard", **meta)

    # ------------------------------------------------------------------ I3 exchange
    def exchange(self, command: int, data: bytes = b"", timeout: float = 30.0,
                 label: str = "") -> tuple[int, bytes]:
        """Broadcast one I3 message on PRIVATE_APP and wait for the matching reply
        (command | 0x80, or REFUSED). Replies are broadcast too, so anything else is
        skipped. Raises RadioError on timeout."""
        if not self.iface:
            raise RadioError("gateway radio is not open")
        msg = pack_message(command, data)
        with self._xlock:
            w = {"expected": {command | 0x80, 0x84}, "frame": None, "meta": None,
                 "event": threading.Event()}
            self._waiter = w
            try:
                t0 = time.time()
                at = airtime_ms(len(msg), self.preset)
                self.iface.sendData(msg, destinationId="^all", portNum=PRIVATE_APP, wantAck=True)
                self.stats["tx"] += 1
                self.stats["airtime_ms"] += at
                BUS.emit("radio.tx", side=self.name, cmd=CMD_NAMES.get(command, hex(command)),
                         size=len(msg), airtime_ms=round(at), label=label, timeout_s=timeout)
                if not w["event"].wait(timeout):
                    BUS.emit("radio.timeout", side=self.name, cmd=CMD_NAMES.get(command),
                             label=label, waited_s=round(time.time() - t0, 1))
                    raise RadioError(f"no {CMD_NAMES.get(command, 'reply')} answer over LoRa "
                                     f"within {timeout:.0f}s")
                rtt = time.time() - t0
                self.stats["airtime_ms"] += airtime_ms(len(w["frame"]), self.preset)
                rcmd, rdata = unpack_message(w["frame"])
                BUS.emit("radio.reply", side=self.name, cmd=CMD_NAMES.get(rcmd, hex(rcmd)),
                         label=label, rtt_ms=round(rtt * 1000), size=len(w["frame"]),
                         **{k: w["meta"][k] for k in ("rssi", "snr", "hops", "from")})
                return rcmd, rdata
            finally:
                self._waiter = None

    def status(self) -> dict:
        return {"up": self.up, "port": self.port, "node": self.node_id,
                "preset": preset_name(self.preset), "region": self.region,
                "stats": {**self.stats, "airtime_ms": round(self.stats["airtime_ms"])},
                "last_rx": self.last_rx}


class RadioTransport:
    """Adapter so lastword_bridge.Flow can use the persistent radio (Flow calls
    transport.exchange(cmd, data))."""
    def __init__(self, radio: MeshRadio, approve_timeout: float):
        self.radio, self.approve_timeout = radio, approve_timeout
        self.label = ""

    def exchange(self, command: int, data: bytes = b""):
        from lastword_bridge.transport import TransportError
        timeout = self.approve_timeout if command == Command.REQUEST else 45.0
        try:
            return self.radio.exchange(command, data, timeout=timeout, label=self.label)
        except RadioError as e:
            raise TransportError(str(e)) from e
