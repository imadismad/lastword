"""LASTWORD operator / agent dashboard (FR-16) — the full showpiece.

A thin FastAPI service on top of the EXISTING agent + bridge. It lets an operator:
  - parametrize the agent: edit policy (caps, currencies, thresholds) + supplier whitelist,
    choose the reader backend (local deterministic, or Bedrock + model id + guardrail);
  - drop in an invoice document (pdf/eml/txt); the agent reads it in quarantine;
  - see the PREPARED transaction: extracted fields, guard verdict, C1-C14 reasons, risk
    score, flags, and the typed proposal — before anything is approved;
  - SUBMIT it to the bridge, which drives the real badge -> live L1 payment, and watch the
    status + the explorer link.

The dashboard holds NO key and NO payment power. It calls the agent pipeline for reading
and the bridge I4 API for anything that touches the badge/chain. Bedrock only works where
reachable (EC2); on the Dell it falls back to the local reader automatically.

Run (on EC2, where Bedrock is reachable):
    uvicorn dashboard.server:app --host 127.0.0.1 --port 8090
Env:
    BRIDGE_URL              (default http://127.0.0.1:8099)   the I4 bridge
    DASH_EXPLORER_URL       (default http://127.0.0.1:3000)   block explorer base
    DASH_WHITELIST_FILE     (default agent/demo/whitelist.json)
    BEDROCK_MODEL_ID, BEDROCK_GUARDRAIL_ID, AWS_DEFAULT_REGION  (optional, for Bedrock)
    LW_MESH_DEV             (e.g. COM8)   the Dell LoRa nugget the bridge drives; enables
                            the "Live demo" (100% hardware) tab's live radio/mesh status.

The "Live demo" tab shows the real LoRa topology (Dell radio -> battery relay -> HP
junction + badge) and runs a quote through the real mesh path. See junction/LIVE_DEMO.md.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import time

import requests
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "proto", "src"))
sys.path.insert(0, os.path.join(ROOT, "agent", "src"))

from lastword_agent.guard import Guard, DEFAULT_POLICY  # noqa: E402
from lastword_agent.reader import make_reader, LocalReader  # noqa: E402
from lastword_agent.schema import READER_SCHEMA  # noqa: E402
import jsonschema  # noqa: E402

BRIDGE_URL = os.environ.get("BRIDGE_URL", "http://127.0.0.1:8099").rstrip("/")
EXPLORER_URL = os.environ.get("DASH_EXPLORER_URL", "http://127.0.0.1:3000").rstrip("/")
WHITELIST_FILE = os.environ.get("DASH_WHITELIST_FILE",
                                os.path.join(ROOT, "agent", "demo", "whitelist.json"))

# ---- Live demo (100% hardware) wiring ---------------------------------------
# The radio this dashboard's bridge drives (the Dell nugget). When the bridge is
# started with BRIDGE_TRANSPORT=mesh:<port>, this is the SAME port. The dashboard
# only READS the radio for status; the bridge owns the actual send.
MESH_DEV = os.environ.get("LW_MESH_DEV", os.environ.get("MESH_DEV", ""))  # e.g. COM8
# Human-readable topology for the Live-demo page (overridable via env, but these
# defaults match the hackathon rig: Dell=bridge radio, nugget-2=battery relay, HP=junction).
TOPOLOGY = {
    "dell": {
        "role": "bridge radio (node 1)",
        "detail": "Dashboard + Bedrock agent + I4 bridge; drives the LoRa nugget on "
                  + (MESH_DEV or "COM8"),
        "dev": MESH_DEV or "COM8",
    },
    "relay": {
        "role": "battery relay (node 2)",
        "detail": "Isolated Meshtastic nugget on an external battery — no PC. Extends "
                  "range and routes I3 frames between the Dell and the HP.",
    },
    "hp": {
        "role": "junction + badge (node 3)",
        "detail": "junction/mesh_junction.py receives each I3 frame off the mesh and "
                  "hands it to the badge (sim P-256 today, hardware chip once badge-fw "
                  "exists), then replies over the mesh.",
    },
}

HERE = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="LASTWORD dashboard", version="1.0.0")


# ----------------------------------------------------------------- live config state
class Config:
    """Mutable agent configuration the operator edits from the UI."""
    def __init__(self):
        self.policy = dict(DEFAULT_POLICY)
        self.policy["allowed_currencies"] = sorted(self.policy["allowed_currencies"])
        self.whitelist = self._load_whitelist()
        self.reader_mode = "local"             # "local" | "bedrock"
        self.bedrock_model = os.environ.get("BEDROCK_MODEL_ID", "")
        self.bedrock_guardrail = os.environ.get("BEDROCK_GUARDRAIL_ID", "")
        self.region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

    def _load_whitelist(self) -> dict:
        try:
            return json.load(open(WHITELIST_FILE))
        except Exception:
            return {}

    def guard(self) -> Guard:
        pol = dict(self.policy)
        pol["allowed_currencies"] = set(pol.get("allowed_currencies", []))
        return Guard(policy=pol, whitelist=self.whitelist)

    def reader(self):
        if self.reader_mode == "bedrock" and self.bedrock_model:
            return make_reader(prefer_bedrock=True, model_id=self.bedrock_model,
                               region=self.region,
                               guardrail_id=self.bedrock_guardrail or None)
        return LocalReader()


CFG = Config()


# ---------------------------------------------------------------- document extraction
def extract_text(filename: str, data: bytes) -> str:
    low = (filename or "").lower()
    if low.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            r = PdfReader(io.BytesIO(data))
            return "\n".join((p.extract_text() or "") for p in r.pages)
        except Exception as e:
            return f"[pdf-extract-failed: {e}]"
    if low.endswith(".eml"):
        import email
        msg = email.message_from_bytes(data)
        parts = []
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    parts.append(part.get_payload(decode=True).decode("utf-8", "ignore"))
        else:
            parts.append(msg.get_payload(decode=True).decode("utf-8", "ignore"))
        return f"From: {msg.get('From','')}\nSubject: {msg.get('Subject','')}\n" + "\n".join(parts)
    return data.decode("utf-8", "ignore")


def evaluate_text(text: str, deadline_mins: int, token: int) -> dict:
    quote_hash = "0x" + hashlib.sha256(text.encode()).hexdigest()
    reader = CFG.reader()
    guard = CFG.guard()
    known = dict(guard.whitelist)
    raw = reader.read(text, known_suppliers=known)
    schema_ok, schema_err = True, None
    try:
        jsonschema.validate(raw, READER_SCHEMA)
    except jsonschema.ValidationError as e:
        schema_ok, schema_err = False, e.message

    v = guard.evaluate(raw, quote_hash)
    deadline = int(time.time()) + deadline_mins * 60
    nonce = int(quote_hash, 16) % (2**31)

    beneficiary = raw.get("beneficiary") or ""
    evm_ok = beneficiary.startswith("0x") and len(beneficiary) == 42

    proposal = None
    if v.verdict == "ASK_BADGE" and evm_ok and schema_ok:
        proposal = {
            "supplier_id": (raw.get("supplier_name") or "unknown")[:128],
            "beneficiary": beneficiary,
            "token": token,
            "amount": int(raw.get("amount") or 0),
            "deadline": deadline,
            "quote_hash": quote_hash,
            "verdict": "ASK_BADGE",
            "nonce": nonce,
            "criteria": v.reasons,
            "flags": v.flags,
            "policy": CFG.policy.get("version", 1),
        }

    return {
        "reader": reader.name,
        "quote_hash": quote_hash,
        "schema_ok": schema_ok,
        "schema_error": schema_err,
        "extracted": raw,
        "verdict": v.verdict,
        "score": v.score,
        "reasons": v.reasons,
        "flags": v.flags,
        "explanation": v.explanation,
        "evm_beneficiary": evm_ok,
        "proposal": proposal,
    }


# ----------------------------------------------------------------------------- models
class ConfigIn(BaseModel):
    policy: dict | None = None
    whitelist: dict | None = None
    reader_mode: str | None = None
    bedrock_model: str | None = None
    bedrock_guardrail: str | None = None
    region: str | None = None


class SubmitIn(BaseModel):
    proposal: dict


# --------------------------------------------------------------------------- endpoints
@app.get("/api/config")
def get_config():
    return {
        "policy": CFG.policy,
        "whitelist": CFG.whitelist,
        "reader_mode": CFG.reader_mode,
        "bedrock_model": CFG.bedrock_model,
        "bedrock_guardrail": CFG.bedrock_guardrail,
        "region": CFG.region,
        "bridge_url": BRIDGE_URL,
        "explorer_url": EXPLORER_URL,
    }


@app.put("/api/config")
def put_config(body: ConfigIn):
    if body.policy is not None:
        CFG.policy.update(body.policy)
        if "allowed_currencies" in CFG.policy and isinstance(CFG.policy["allowed_currencies"], list):
            CFG.policy["allowed_currencies"] = sorted(set(CFG.policy["allowed_currencies"]))
    if body.whitelist is not None:
        CFG.whitelist = body.whitelist
    if body.reader_mode in ("local", "bedrock"):
        CFG.reader_mode = body.reader_mode
    if body.bedrock_model is not None:
        CFG.bedrock_model = body.bedrock_model
    if body.bedrock_guardrail is not None:
        CFG.bedrock_guardrail = body.bedrock_guardrail
    if body.region:
        CFG.region = body.region
    return get_config()


@app.post("/api/evaluate")
async def evaluate(file: UploadFile = File(...), deadline_mins: int = Form(10),
                   token: int = Form(0)):
    data = await file.read()
    text = extract_text(file.filename, data)
    result = evaluate_text(text, deadline_mins, token)
    result["document_preview"] = text[:1500]
    result["filename"] = file.filename
    return result


@app.post("/api/evaluate_text")
def evaluate_text_endpoint(body: dict):
    text = body.get("text", "")
    result = evaluate_text(text, int(body.get("deadline_mins", 10)),
                           int(body.get("token", 0)))
    result["document_preview"] = text[:1500]
    return result


@app.post("/api/submit")
def submit(body: SubmitIn):
    """Post the prepared proposal to the bridge -> real badge -> live L1 payment."""
    try:
        r = requests.post(f"{BRIDGE_URL}/proposals", json=body.proposal, timeout=15)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"bridge unreachable: {e}")
    if not r.ok:
        raise HTTPException(status_code=r.status_code,
                            detail=r.json().get("detail") if r.content else "bridge error")
    return r.json()


@app.get("/api/status/{req_id}")
def status(req_id: int):
    try:
        r = requests.get(f"{BRIDGE_URL}/proposals/{req_id}", timeout=10)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"bridge unreachable: {e}")
    if not r.ok:
        raise HTTPException(status_code=r.status_code, detail="unknown reqId")
    data = r.json()
    # build explorer links for whatever tx hashes exist
    tx = data.get("tx", {})
    links = {step: f"{EXPLORER_URL}/tx/{h}" for step, h in tx.items()}
    data["explorer_links"] = links
    return data


@app.get("/api/bridge_health")
def bridge_health():
    try:
        r = requests.get(f"{BRIDGE_URL}/health", timeout=5)
        return {"up": r.ok, "detail": r.json() if r.content else {}}
    except Exception as e:
        return {"up": False, "detail": str(e)}


@app.get("/api/transport")
def get_transport():
    """Read the bridge's active badge transport (simulated TCP vs real LoRa mesh)."""
    try:
        r = requests.get(f"{BRIDGE_URL}/transport", timeout=5)
    except Exception as e:
        return {"available": False, "detail": f"bridge unreachable: {e}"}
    if not r.ok:
        # older bridge without the toggle endpoint
        return {"available": False, "detail": "bridge has no transport endpoint"}
    return {"available": True, **r.json()}


@app.put("/api/transport")
def put_transport(body: dict):
    """Switch the bridge transport. Body: {"mode":"simulated"|"real"} or {"spec":"..."}.

    Switching re-provisions the badge on the new transport (the TCP sim and the mesh/HP
    badge are different instances), which can take ~15s for the mesh path.
    """
    try:
        r = requests.put(f"{BRIDGE_URL}/transport", json=body, timeout=40)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"bridge unreachable: {e}")
    if not r.ok:
        detail = r.json().get("detail") if r.content else "bridge error"
        raise HTTPException(status_code=r.status_code, detail=detail)
    return r.json()


# --------------------------------------------------------- Live demo (hardware)
_MESH_CACHE = {"t": 0.0, "data": None}


def _read_mesh(dev: str) -> dict:
    """Open the local LoRa nugget read-only and report identity / region / peers.

    Opening a Meshtastic serial node takes ~10-15s, so results are cached briefly.
    The bridge may hold the port exclusively when BRIDGE_TRANSPORT=mesh:<dev>; in that
    case the open fails and we report 'busy' rather than erroring the whole page.
    """
    import meshtastic.serial_interface
    iface = meshtastic.serial_interface.SerialInterface(devPath=dev)
    try:
        ni = iface.getMyNodeInfo() or {}
        user = ni.get("user") or {}
        out = {"dev": dev, "reachable": True,
               "node_id": user.get("id"), "name": user.get("longName"),
               "hw": user.get("hwModel")}
        try:
            lc = iface.localNode.localConfig.lora
            out["region"] = int(lc.region)
            out["modem_preset"] = int(lc.modem_preset)
            out["hop_limit"] = int(lc.hop_limit)
        except Exception:
            pass
        try:
            out["channel_url"] = iface.localNode.getURL()
        except Exception:
            pass
        peers = []
        for n in (iface.nodes or {}).values():
            u = n.get("user", {}) or {}
            if u.get("id") and u.get("id") != out.get("node_id"):
                peers.append({"id": u.get("id"), "name": u.get("longName")})
        out["peers"] = peers
        return out
    finally:
        iface.close()


@app.get("/api/livedemo/topology")
def livedemo_topology():
    return {
        "topology": TOPOLOGY,
        "mesh_dev": MESH_DEV,
        "bridge_url": BRIDGE_URL,
        "explorer_url": EXPLORER_URL,
        "reader_mode": CFG.reader_mode,
        "bedrock_model": CFG.bedrock_model,
    }


@app.get("/api/mesh/status")
def mesh_status(dev: str | None = None, refresh: int = 0):
    dev = (dev or MESH_DEV or "").strip()
    if not dev:
        return {"configured": False,
                "detail": "no radio configured — set LW_MESH_DEV=COM8 (the Dell nugget "
                          "the bridge drives) to enable live mesh status"}
    now = time.time()
    if not refresh and _MESH_CACHE["data"] and now - _MESH_CACHE["t"] < 20 \
            and _MESH_CACHE["data"].get("dev") == dev:
        return {"configured": True, "cached": True, **_MESH_CACHE["data"]}
    try:
        data = _read_mesh(dev)
    except Exception as e:
        # the bridge likely holds the port (mesh transport) — that's expected & GOOD
        return {"configured": True, "reachable": False, "dev": dev,
                "detail": f"radio busy or unreachable: {e}. If the bridge is running with "
                          f"BRIDGE_TRANSPORT=mesh:{dev}, it owns the port and will transmit "
                          f"when you submit — that is the hardware path working."}
    _MESH_CACHE["t"], _MESH_CACHE["data"] = now, data
    return {"configured": True, "cached": False, **data}


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(HERE, "index.html"), encoding="utf-8") as f:
        return f.read()
