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


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(HERE, "index.html"), encoding="utf-8") as f:
        return f.read()
