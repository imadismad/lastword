"""LASTWORD 2.0 hub API.

    python -m uvicorn hub.app:app --app-dir lw2 --host 127.0.0.1 --port 8100

REST for actions, one WebSocket (/ws) for the live event stream, and the built UI
(lw2/web/dist) served at /."""
from __future__ import annotations

import asyncio
import glob
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in ("proto/src", "agent/src", "bridge/src"):
    sys.path.insert(0, os.path.join(ROOT, _p))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from lastword_bridge.journal import Journal  # noqa: E402

from . import devices  # noqa: E402
from .events import BUS  # noqa: E402
from .pipeline import Core, EXPLORER  # noqa: E402

app = FastAPI(title="LASTWORD 2.0 hub", version="2.0.0")
CORE: Core | None = None
BOOT_ERROR: str | None = None
STATION: dict = {"last": None}
DIST = os.path.join(ROOT, "lw2", "web", "dist")


@app.on_event("startup")
async def _startup():
    global CORE, BOOT_ERROR
    BUS.bind(asyncio.get_running_loop())
    port = devices.gateway_port()
    if not port:
        BOOT_ERROR = "gateway nugget (nugget-1) not found on USB"
        BUS.emit("hub.error", detail=BOOT_ERROR)
        return
    try:
        CORE = Core(port)
        CORE.station_ready = lambda: bool(STATION["last"]) and time.time() - STATION["last"]["ts"] < 12
        await asyncio.to_thread(CORE.start)
    except Exception as e:
        BOOT_ERROR = f"{type(e).__name__}: {e}"
        BUS.emit("hub.error", detail=BOOT_ERROR)


def core() -> Core:
    if CORE is None:
        raise HTTPException(503, BOOT_ERROR or "hub starting")
    return CORE


# ------------------------------------------------------------------- read models
@app.get("/api/state")
def state():
    c = CORE
    chain = {}
    if c:
        try:
            chain = {"block": c.chain.w3.eth.block_number, "chain_id": c.chain.chain_id,
                     "contract": c.contract_addr, "explorer": EXPLORER, "up": True}
        except Exception as e:
            chain = {"up": False, "detail": str(e)[:120]}
    st = STATION["last"]
    return {
        "boot_error": BOOT_ERROR,
        "devices": devices.inventory(),
        "radio": c.radio.status() if c else None,
        "badge": c.badge if c else None,
        "station": {**st, "age_s": round(time.time() - st["ts"], 1)} if st else None,
        "chain": chain,
        "agent": {"reader": c.agent.reader_mode if c else None},
    }


@app.get("/api/events")
def events(n: int = 200):
    return BUS.recent(n)


@app.get("/api/samples")
def samples():
    out = []
    titles = {"inv1": "Legit · ACME Steel", "inv2": "Legit · Port Logistics",
              "inv3": "Swapped payout address", "inv4": "Hidden prompt injection",
              "inv5": "Unknown supplier", "inv6": "Over per-transaction cap"}
    for f in sorted(glob.glob(os.path.join(ROOT, "dashboard", "invoices", "inv*.txt"))):
        key = os.path.basename(f).split("_")[0]
        text = open(f, encoding="utf-8").read()
        text = "\n".join(l for l in text.splitlines() if not l.startswith("Expected:")).strip()
        out.append({"id": key, "title": titles.get(key, key), "text": text})
    return out


@app.get("/api/payments")
def payments():
    c = core()
    res = []
    for reqId, p in sorted(c.flow.proposals.items(), key=lambda kv: -kv[0]):
        rec = c.flow.payments.get(reqId, {})
        res.append({"reqId": reqId, "status": p.status.value, "detail": p.detail, "tx": p.tx,
                    "amount": p.intent.amount, "beneficiary": "0x" + p.intent.beneficiary.hex(),
                    "steps": rec.get("steps", {})})
    return res


@app.get("/api/journal")
def journal(n: int = 30):
    c = core()
    ok, bad_at, msg = Journal.verify(c.journal_path)
    entries = Journal.read_all(c.journal_path)
    root = Journal.merkle_root(c.journal_path) if entries else None
    return {"verified": ok, "broken_at": bad_at, "detail": msg, "count": len(entries),
            "merkle_root": root, "tail": entries[-n:][::-1]}


# ------------------------------------------------------------------- actions
class EvalIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    deadline_mins: int = Field(default=15, ge=1, le=120)


@app.post("/api/evaluate")
def evaluate(body: EvalIn):
    return core().agent.evaluate(body.text, body.deadline_mins)


class PayIn(BaseModel):
    proposal: dict


@app.post("/api/pay")
def pay(body: PayIn):
    try:
        return {"reqId": core().pay(body.proposal)}
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@app.post("/api/provision")
async def provision():
    try:
        return await asyncio.to_thread(core().provision)
    except Exception as e:
        raise HTTPException(502, f"{type(e).__name__}: {e}")


@app.post("/api/attack/{kind}")
async def attack(kind: str):
    try:
        return await asyncio.to_thread(core().attack, kind)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(409, str(e))


class IngestIn(BaseModel):
    model_config = {"extra": "allow"}
    type: str = Field(pattern=r"^(station|badge)\.[a-z_]+$")


@app.post("/api/ingest")
def ingest(body: IngestIn):
    """Telemetry from the badge station (display only, never used for a decision)."""
    data = body.model_dump()
    t = data.pop("type")
    if t == "station.heartbeat":
        STATION["last"] = {**data, "ts": time.time()}
        return {"ok": True}
    if t == "station.rx" and CORE:
        CORE.radio.note_station_rx()
    BUS.emit(t, **data)
    return {"ok": True}


# ------------------------------------------------------------------- live stream
@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    q = BUS.subscribe()
    try:
        await sock.send_json({"type": "hello", "recent": BUS.recent(150)})
        while True:
            await sock.send_json(await q.get())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        BUS.unsubscribe(q)


# ------------------------------------------------------------------- UI
if os.path.isdir(os.path.join(DIST, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST, "assets")), name="assets")


@app.get("/{path:path}")
def spa(path: str):
    index = os.path.join(DIST, "index.html")
    asset = os.path.normpath(os.path.join(DIST, path))
    if path and asset.startswith(os.path.normpath(DIST) + os.sep) and os.path.isfile(asset):
        return FileResponse(asset)  # files from web/public (favicon…)
    if not os.path.exists(index):
        raise HTTPException(404, "UI not built: cd lw2/web && npm install && npm run build")
    return FileResponse(index)
