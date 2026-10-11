"""One-shot: dump the Dell radio's node DB with last-heard times + live-listen briefly.

Prints each node id, name, snr, and seconds-since-last-heard, so we can tell which peers
are being heard RIGHT NOW vs stale DB entries. Then it subscribes for ~20s and prints any
packet it receives live (that is the only proof a node is in range on the SAME channel).
"""
import sys, time

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM6"
LISTEN = int(sys.argv[2]) if len(sys.argv) > 2 else 25

import meshtastic.serial_interface
from pubsub import pub

iface = meshtastic.serial_interface.SerialInterface(devPath=PORT)
try:
    me = (iface.getMyNodeInfo() or {}).get("user", {})
    print(f"ME: {me.get('longName','?')} ({me.get('id','?')}) on {PORT}")
    try:
        lc = iface.localNode.localConfig.lora
        print(f"LORA: region={lc.region} preset={lc.modem_preset} hop={lc.hop_limit}")
    except Exception as e:
        print(f"LORA: (unreadable: {e})")
    try:
        print(f"CHANNEL_URL: {iface.localNode.getURL()}")
    except Exception as e:
        print(f"CHANNEL_URL: (unreadable: {e})")

    now = time.time()
    print("\nNODE DB (lastHeard):")
    for n in (iface.nodes or {}).values():
        u = n.get("user", {}) or {}
        lh = n.get("lastHeard")
        age = (f"{int(now - lh)}s ago" if lh else "never")
        snr = n.get("snr")
        print(f"  {u.get('id','?'):14} {u.get('longName','?'):22} lastHeard={age:12} snr={snr}")

    print(f"\nLIVE LISTEN for {LISTEN}s (any packet = a node transmitting on THIS channel in range):")
    got = {"n": 0}

    def on_rx(packet, interface):
        got["n"] += 1
        src = packet.get("fromId") or packet.get("from")
        pn = (packet.get("decoded", {}) or {}).get("portnum")
        print(f"  RX from {src} portnum={pn} rssi={packet.get('rxRssi')} snr={packet.get('rxSnr')}")

    pub.subscribe(on_rx, "meshtastic.receive")
    t0 = time.time()
    while time.time() - t0 < LISTEN:
        time.sleep(0.5)
    print(f"LIVE PACKETS RECEIVED: {got['n']}")
finally:
    iface.close()
