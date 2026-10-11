"""Start LASTWORD 2.0: the hub (agent + bridge + gateway radio + UI) and the badge station
(nugget-3 + badge) as two separate processes, then open http://127.0.0.1:8100.

    .venv\\Scripts\\python.exe lw2\\run.py              # real badge (auto-detected)
    .venv\\Scripts\\python.exe lw2\\run.py --badge sim  # software P-256 badge (announced fallback)

Needs the L1 tunnel (-L 9650) and .env (contract, RPC, BRIDGE/AGENT keys)."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
DATA = os.path.join(ROOT, "lw2", "data")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--badge", default="", help="badge COM port, or 'sim'")
    ap.add_argument("--port", type=int, default=8100)
    a = ap.parse_args()
    os.makedirs(DATA, exist_ok=True)
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8",
           "LW_HUB_URL": f"http://127.0.0.1:{a.port}"}

    hub = subprocess.Popen(
        [PY, "-m", "uvicorn", "hub.app:app", "--app-dir", os.path.join(ROOT, "lw2"),
         "--host", "127.0.0.1", "--port", str(a.port)],
        cwd=ROOT, env=env, stdout=open(os.path.join(DATA, "hub.log"), "w"), stderr=subprocess.STDOUT)
    time.sleep(3)
    station = subprocess.Popen(
        [PY, os.path.join(ROOT, "lw2", "station", "badge_station.py")]
        + (["--badge", a.badge] if a.badge else []),
        cwd=ROOT, env=env, stdout=open(os.path.join(DATA, "station.log"), "w"),
        stderr=subprocess.STDOUT)
    print(f"LASTWORD 2.0 -> http://127.0.0.1:{a.port}   (logs in lw2/data/*.log, Ctrl-C to stop)")
    try:
        while hub.poll() is None and station.poll() is None:
            time.sleep(1)
        print("a process exited:", "hub" if hub.poll() is not None else "station")
    except KeyboardInterrupt:
        pass
    finally:
        for p in (station, hub):
            p.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
