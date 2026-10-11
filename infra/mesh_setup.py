"""Inspect / align the LoRa nuggets for the 100%-hardware Live Demo.

The three nuggets must share the SAME primary channel + region + modem preset to talk.
This tool:
  --info COMx            : print a node's identity, LoRa region/preset, channel URL, peers
  --url COMx             : print just the primary-channel URL (paste into the other nodes)
  --apply COMx <URL>     : set a node's primary channel to <URL> (align all three)
  --ping COMx            : open the node and confirm it is reachable (no config change)

Topology for the demo (Option A, all hardware):
  Dell  = bridge radio   (mesh:COMx)              -> this PC
  Nugget 2 = battery relay (no PC; just powered)  -> extends range, routes frames
  HP    = junction + badge (junction/mesh_junction.py --dev COMy)

Usage:
    python infra/mesh_setup.py --info COM8
    python infra/mesh_setup.py --url COM8
    python infra/mesh_setup.py --apply COM6 "https://meshtastic.org/e/#...."
"""
import argparse
import json
import sys
import time


def _iface(port):
    import meshtastic.serial_interface
    return meshtastic.serial_interface.SerialInterface(devPath=port)


def info(port):
    iface = _iface(port)
    try:
        ni = iface.getMyNodeInfo() or {}
        user = ni.get("user") or {}
        print(f"node   : {user.get('longName','?')} ({user.get('id','?')})  hw={user.get('hwModel','?')}")
        try:
            lc = iface.localNode.localConfig.lora
            print(f"lora   : region={lc.region} modem={lc.modem_preset} hop={lc.hop_limit}")
        except Exception as e:
            print(f"lora   : (could not read: {e})")
        try:
            url = iface.localNode.getURL()
            print(f"ch url : {url}")
        except Exception as e:
            print(f"ch url : (could not read: {e})")
        peers = [n for n in (iface.nodes or {}).values()]
        print(f"peers  : {len(peers)} node(s) in db")
        for n in peers:
            u = n.get("user", {})
            print(f"         {u.get('id','?')}  {u.get('longName','?')}")
    finally:
        iface.close()


def url(port):
    iface = _iface(port)
    try:
        print(iface.localNode.getURL())
    finally:
        iface.close()


def apply(port, channel_url):
    iface = _iface(port)
    try:
        print(f"applying channel URL to {port} ...")
        iface.localNode.setURL(channel_url)
        print("done. the node will use the shared primary channel.")
    finally:
        iface.close()


def ping(port):
    try:
        iface = _iface(port)
    except Exception as e:
        print(f"UNREACHABLE {port}: {e}")
        return 2
    try:
        ni = iface.getMyNodeInfo() or {}
        u = ni.get("user") or {}
        print(f"REACHABLE {port}: {u.get('longName','?')} ({u.get('id','?')})")
        return 0
    finally:
        iface.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--info")
    ap.add_argument("--url")
    ap.add_argument("--ping")
    ap.add_argument("--apply", nargs=2, metavar=("COMx", "URL"))
    a = ap.parse_args()
    if a.info:
        info(a.info)
    elif a.url:
        url(a.url)
    elif a.ping:
        return ping(a.ping)
    elif a.apply:
        apply(a.apply[0], a.apply[1])
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
