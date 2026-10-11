"""Listen on nugget-1 (COM6) for live packets, flag when nugget-2 (0d60) is heard.

Writes progress to a file so we can read it mid-run without the serial contention.
"""
import sys, time

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM6"
LISTEN = int(sys.argv[2]) if len(sys.argv) > 2 else 90
OUT = sys.argv[3] if len(sys.argv) > 3 else r"C:\Users\Dell_Arte_III\Desktop\hackathon_essec_secure_horizon\hear.txt"
TARGET = "0d60"  # nugget-2 short id

import meshtastic.serial_interface
from pubsub import pub

log = open(OUT, "w", encoding="utf-8")
def w(s):
    log.write(s + "\n"); log.flush()
    print(s, flush=True)

iface = meshtastic.serial_interface.SerialInterface(devPath=PORT)
try:
    me = (iface.getMyNodeInfo() or {}).get("user", {})
    w(f"ME: {me.get('longName','?')} ({me.get('id','?')}) on {PORT}")
    try:
        w(f"MY_CHANNEL_URL: {iface.localNode.getURL()}")
    except Exception as e:
        w(f"MY_CHANNEL_URL: (unreadable: {e})")
    hits = {"target": 0, "any": 0}

    def on_rx(packet, interface):
        hits["any"] += 1
        src = packet.get("fromId") or packet.get("from") or "?"
        pn = (packet.get("decoded", {}) or {}).get("portnum")
        line = f"RX #{hits['any']} from {src} portnum={pn} rssi={packet.get('rxRssi')} snr={packet.get('rxSnr')}"
        if TARGET in str(src):
            hits["target"] += 1
            line += "  <<< THIS IS NUGGET-2 (0d60) — HEARD LIVE!"
        w(line)

    pub.subscribe(on_rx, "meshtastic.receive")
    w(f"LISTENING {LISTEN}s for live packets (nugget-2 beacons every ~1-3 min)...")
    t0 = time.time()
    while time.time() - t0 < LISTEN:
        time.sleep(1)
        if int(time.time() - t0) % 15 == 0:
            w(f"  ...{int(time.time()-t0)}s elapsed, packets so far: any={hits['any']} nugget2={hits['target']}")
    w(f"DONE. total packets any={hits['any']} nugget2={hits['target']}")
    w("RESULT: " + ("NUGGET-2 HEARD" if hits["target"] else ("heard other nodes but NOT nugget-2" if hits["any"] else "heard NOTHING at all")))
finally:
    iface.close()
    log.close()
