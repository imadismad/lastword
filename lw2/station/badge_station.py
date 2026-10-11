"""LASTWORD 2.0 badge station: nugget-3 <-> CDC badge (TROPIC01), on the same Dell.

Replaces the HP junction. It is a SEPARATE process from the hub on purpose: it holds no
key, cannot read the sealed frames, and only moves bytes between the LoRa node and the
badge (the badge decrypts, verifies the gateway signature, shows the intent and signs
after the PIN). It reports what it sees to the hub for display only.

    python lw2/station/badge_station.py                    # auto-detect nugget-3 + badge
    python lw2/station/badge_station.py --nugget COM10 --badge COM9
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in ("proto/src", "bridge/src", "junction", "badge-sim", "lw2"):
    sys.path.insert(0, os.path.join(ROOT, p))

import requests  # noqa: E402

from lastword_proto import unpack_message, pack_message, Command  # noqa: E402
from hub import devices  # noqa: E402
from hub.airtime import airtime_ms  # noqa: E402

PRIVATE_APP = 256
HUB = os.environ.get("LW_HUB_URL", "http://127.0.0.1:8100").rstrip("/")
APPROVE_S = os.environ.setdefault("JUNCTION_APPROVE_S", "120")
NAMES = {0x01: "HELLO", 0x81: "HELLO_OK", 0x02: "PROVISION", 0x82: "PROV_OK",
         0x03: "REQUEST", 0x83: "RESPONSE", 0x84: "REFUSED"}


def report(type_: str, **data):
    """Fire-and-forget telemetry to the hub (display only)."""
    def _post():
        try:
            requests.post(f"{HUB}/api/ingest", json={"type": type_, **data}, timeout=2)
        except Exception:
            pass
    threading.Thread(target=_post, daemon=True).start()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nugget", default="", help="nugget-3 COM port (default: by USB serial)")
    ap.add_argument("--badge", default="", help="badge COM port, or 'sim' for the software badge")
    a = ap.parse_args()

    nugget = a.nugget or devices.station_port()
    badge_spec = a.badge or devices.badge_port()
    if not nugget:
        sys.exit("nugget-3 not found (set --nugget or LW_STATION_NUGGET_SERIAL)")
    if not badge_spec:
        sys.exit("badge not found (set --badge COMx, or --badge sim)")

    from mesh_junction import SerialBadge, SimBadge
    badge = SimBadge(auto=True) if badge_spec == "sim" else SerialBadge(badge_spec)
    software = badge_spec == "sim"
    lock = threading.Lock()

    import meshtastic.serial_interface
    from pubsub import pub

    print(f"[station] badge: {badge.label}")
    # Warm up over USB: enter the binary channel and read the role keys now, so the
    # first HELLO arriving over LoRa is answered in seconds rather than ~17 s.
    try:
        t0 = time.time()
        c, keys = unpack_message(badge.handle(pack_message(Command.HELLO)))
        if c == Command.HELLO_OK and len(keys) == 192:
            print(f"[station] badge online in {time.time() - t0:.1f}s: stock={keys[:8].hex()}.. "
                  f"daf={keys[64:72].hex()}..")
            report("badge.online", stock=keys[:32].hex()[:16], daf=keys[64:96].hex()[:16],
                   hardware=badge_spec != "sim")
    except Exception as e:
        print(f"[station] badge warm-up failed: {e}")
        report("badge.error", cmd="HELLO", detail=f"warm-up: {e}"[:200])
    print(f"[station] opening nugget-3 on {nugget} ...")
    iface = meshtastic.serial_interface.SerialInterface(devPath=nugget)
    me = ((iface.getMyNodeInfo() or {}).get("user") or {}).get("id")
    preset = 0
    try:
        preset = int(iface.localNode.localConfig.lora.modem_preset)
    except Exception:
        pass
    state = {"busy": None}

    def serve(frame: bytes, src, meta):
        cmd = unpack_message(frame)[0]
        name = NAMES.get(cmd, hex(cmd))
        t0 = time.time()
        with lock:
            state["busy"] = name
            if cmd == Command.REQUEST:
                report("badge.awaiting_human", timeout_s=int(APPROVE_S),
                       hint="Y -> PIN -> Y on the badge")
            try:
                resp = badge.handle(frame)
            except Exception as e:
                state["busy"] = None
                print(f"[station] badge error: {e}")
                report("badge.error", cmd=name, detail=str(e)[:200])
                return
            state["busy"] = None
        rcmd = unpack_message(resp)[0]
        report("badge.answered", cmd=NAMES.get(rcmd, hex(rcmd)), size=len(resp),
               badge_ms=round((time.time() - t0) * 1000), to=name)
        # broadcast reply: DMs get PKI-encrypted and dropped (NO_CHANNEL)
        iface.sendData(resp, destinationId="^all", portNum=PRIVATE_APP, wantAck=True)
        report("station.tx", cmd=NAMES.get(rcmd, hex(rcmd)), size=len(resp),
               airtime_ms=round(airtime_ms(len(resp), preset)))
        print(f"[station] {name} -> {NAMES.get(rcmd, hex(rcmd))} ({len(resp)} B) in "
              f"{time.time() - t0:.1f}s")

    def on_rx(packet, interface):
        if interface is not iface:
            return
        dec = packet.get("decoded") or {}
        if dec.get("portnum") not in ("PRIVATE_APP", PRIVATE_APP) or not dec.get("payload"):
            return
        frame = bytes(dec["payload"])
        try:
            cmd = unpack_message(frame)[0]
        except Exception:
            return
        if cmd & 0x80:
            return  # a broadcast reply (ours or another station's), not a request
        hs, hl = packet.get("hopStart"), packet.get("hopLimit")
        meta = {"rssi": packet.get("rxRssi"), "snr": packet.get("rxSnr"),
                "hops": (hs - hl) if hs is not None and hl is not None else None}
        report("station.rx", cmd=NAMES.get(cmd, hex(cmd)), size=len(frame),
               src=packet.get("fromId"), **meta)
        print(f"[station] <- {NAMES.get(cmd, hex(cmd))} {len(frame)} B from "
              f"{packet.get('fromId')} rssi={meta['rssi']} snr={meta['snr']}")
        threading.Thread(target=serve, args=(frame, packet.get("fromId"), meta),
                         daemon=True).start()

    pub.subscribe(on_rx, "meshtastic.receive")
    print(f"[station] node {me} up on {nugget}; relaying PRIVATE_APP <-> badge")

    def heartbeat():
        while True:
            report("station.heartbeat", node=me, nugget=nugget,
                   badge=("software P-256 (sim)" if software else badge_spec),
                   hardware=not software, busy=state["busy"])
            time.sleep(4)
    threading.Thread(target=heartbeat, daemon=True).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[station] stopping")
    finally:
        iface.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
