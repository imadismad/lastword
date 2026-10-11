"""HP side, one shot: find nugget-3, pair it on the shared LASTWORD channel, verify, and
(optionally) start the mesh junction.

    python infra/hp_nugget3.py                     # detect + pair + verify
    python infra/hp_nugget3.py --run               # ... then start the junction (badge sim)
    python infra/hp_nugget3.py --run --badge serial:COM7   # real badge-fw chip on COM7
    python infra/hp_nugget3.py --port COM5 --run   # force the nugget port

Pairing = same primary channel (PSK) + region EU_868 + preset LONG_FAST + hop 3 +
frequency offset as nugget-1 (Dell) and nugget-2 (battery relay).
"""
from __future__ import annotations

import argparse
import base64
import os
import subprocess
import sys
import time

CHANNEL_URL = "https://meshtastic.org/e/#CgcSAQE6AggNEhQIATUAAKBBOANAA0gBUBtoAcAGAQ"
KNOWN = {"12b10afc": "nugget-1 (Dell)", "12b10d60": "nugget-2 (relay)"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_port() -> str:
    from serial.tools import list_ports
    ports = [p for p in list_ports.comports() if p.vid == 0x1A86]  # CH34x = LoRa nugget
    if len(ports) == 1:
        return ports[0].device
    found = ", ".join(f"{p.device} (serial {p.serial_number})" for p in ports) or "none"
    sys.exit(f"cannot pick the nugget automatically — CH34x ports: {found}. Use --port COMx.")


def channel_key(url: str):
    """The settings that must match between nodes (bw/sf/cr are ignored with use_preset)."""
    from meshtastic.protobuf import apponly_pb2
    b64 = url.split("#", 1)[1]
    cs = apponly_pb2.ChannelSet()
    cs.ParseFromString(base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)))
    l, s = cs.lora_config, cs.settings[0]
    return (s.psk, s.name, l.use_preset, l.modem_preset, l.region, l.hop_limit,
            round(l.frequency_offset, 3), l.channel_num)


def pair(port: str) -> None:
    import meshtastic.serial_interface
    want = channel_key(CHANNEL_URL)
    iface = meshtastic.serial_interface.SerialInterface(devPath=port)
    try:
        me = (iface.getMyNodeInfo() or {}).get("user", {})
        print(f"[nugget-3] {me.get('longName', '?')} ({me.get('id', '?')}) on {port}")
        if channel_key(iface.localNode.getURL()) == want:
            print("[nugget-3] already on the LASTWORD channel")
            return
        print("[nugget-3] applying the LASTWORD channel (the node reboots)...")
        iface.localNode.setURL(CHANNEL_URL)
    finally:
        iface.close()
    time.sleep(20)  # let the node reboot before re-reading
    iface = meshtastic.serial_interface.SerialInterface(devPath=port)
    try:
        if channel_key(iface.localNode.getURL()) != want:
            sys.exit("[nugget-3] channel still differs after apply — replug the nugget and retry")
        print("[nugget-3] paired: EU_868 / LONG_FAST / hop 3 / shared PSK")
    finally:
        iface.close()


def listen(port: str, seconds: int) -> None:
    """Optional sanity check: show which other nuggets are heard live."""
    import meshtastic.serial_interface
    from pubsub import pub
    heard = set()

    def on_rx(packet, interface):
        src = (packet.get("fromId") or "").lstrip("!")
        if src in KNOWN and src not in heard:
            heard.add(src)
            print(f"[nugget-3] heard {KNOWN[src]} live (rssi={packet.get('rxRssi')})")

    pub.subscribe(on_rx, "meshtastic.receive")
    iface = meshtastic.serial_interface.SerialInterface(devPath=port)
    try:
        iface.sendText("lw nugget-3 up")  # nugget-1/2 log this if they hear us
        time.sleep(seconds)
    finally:
        iface.close()
    if not heard:
        print("[nugget-3] nothing heard yet (normal if nobody transmitted) — "
              "the Dell's 'Real LoRa' toggle is the real test")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="nugget-3 COM port (default: auto-detect)")
    ap.add_argument("--listen", type=int, default=0, help="listen N s for nugget-1/2")
    ap.add_argument("--run", action="store_true", help="start the junction after pairing")
    ap.add_argument("--badge", default="sim", help="sim | serial:COMx | tcp:host:port")
    a = ap.parse_args()

    port = a.port or find_port()
    pair(port)
    if a.listen:
        listen(port, a.listen)
    if not a.run:
        print(f"next: python junction/mesh_junction.py --dev {port} --badge {a.badge}"
              + (" --auto" if a.badge == "sim" else ""))
        return 0
    cmd = [sys.executable, os.path.join(ROOT, "junction", "mesh_junction.py"),
           "--dev", port, "--badge", a.badge] + (["--auto"] if a.badge == "sim" else [])
    print("[junction] " + " ".join(cmd))
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
