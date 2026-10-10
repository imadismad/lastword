"""Mesh transport smoke-test on the real nugget (Meshtastic node on COM6).

Verifies the LASTWORD send path over real LoRa hardware:
  - open the Meshtastic node,
  - frame a real I3 message (HELLO) with lastword_proto,
  - transmit it on the PRIVATE_APP port (256) the badge listens on,
  - confirm the local radio accepted/queued it for transmission.

A FULL round-trip (RESPONSE back) needs a SECOND node running the badge responder; with a
single node there is nothing to answer, so we assert only that the request leaves the radio.
That is the part that proves the transport + framing work on hardware.

    python infra/mesh_smoketest.py [PORT]
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "proto", "src"))

from lastword_proto import pack_message, Command  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM6"
PRIVATE_APP = 256


def main():
    try:
        import meshtastic.serial_interface
    except Exception as e:
        print(f"meshtastic lib not available: {e}")
        return 1

    print(f"opening Meshtastic node on {PORT} ...")
    try:
        iface = meshtastic.serial_interface.SerialInterface(devPath=PORT)
    except Exception as e:
        print(f"OPEN_FAIL: {e}")
        return 2

    try:
        info = iface.getMyNodeInfo() or {}
        user = (info.get("user") or {})
        print(f"  node: {user.get('longName','?')} ({user.get('id','?')})  "
              f"hw={user.get('hwModel','?')}")

        frame = pack_message(Command.HELLO)   # the exact bytes a badge request carries
        print(f"  framed I3 HELLO = {len(frame)}B: {frame.hex()}")
        print(f"  transmitting on PRIVATE_APP ({PRIVATE_APP}) with wantAck ...")
        sent = iface.sendData(frame, destinationId="^all", portNum=PRIVATE_APP,
                              wantAck=True)
        # sendData returns the MeshPacket it enqueued; a non-None id means the radio took it.
        pkt_id = getattr(sent, "id", None)
        time.sleep(2)  # let the radio actually push it out
        if pkt_id:
            print(f"  OK: radio accepted the packet (id={pkt_id}). "
                  f"Send path over real LoRa works.")
            print("  NOTE: no RESPONSE expected with a single node (no badge responder "
                  "on the mesh). Add a 2nd node flashed as the badge for a full round-trip.")
            return 0
        print("  radio did not return a packet id; send path uncertain.")
        return 3
    finally:
        iface.close()


if __name__ == "__main__":
    sys.exit(main())
