"""Agent orchestration: read -> validate schema -> guard -> post proposal to the bridge.

The agent has no key and no payment power. It reaches the bridge only through the I4
local API and can send only a typed proposal. It receives back only a status.
"""
from __future__ import annotations

import hashlib
import json

import jsonschema
import requests

from .guard import Guard, Verdict
from .reader import make_reader, LocalReader
from .schema import READER_SCHEMA


class Agent:
    def __init__(self, bridge_url: str, guard: Guard, reader=None):
        self.bridge_url = bridge_url.rstrip("/")
        self.guard = guard
        self.reader = reader or LocalReader()

    def process(self, quote_text: str, deadline: int, token: int = 0,
                nonce: int | None = None) -> dict:
        """Full pipeline for one quote. Returns a result dict (verdict + bridge status)."""
        quote_hash = "0x" + hashlib.sha256(quote_text.encode()).hexdigest()

        # 1. isolated read, then STRICT schema validation (reject anything off-schema)
        known = {s: v for s, v in self.guard.whitelist.items()}
        raw = self.reader.read(quote_text, known_suppliers=known)
        try:
            jsonschema.validate(raw, READER_SCHEMA)
        except jsonschema.ValidationError as e:
            return {"verdict": "REJECT", "reason": f"reader output off-schema: {e.message}",
                    "posted": False}

        # 2. guard: criteria + score + verdict
        v: Verdict = self.guard.evaluate(raw, quote_hash)

        result = {
            "quote_hash": quote_hash,
            "reader": self.reader.name,
            "extracted": raw,
            "verdict": v.verdict,
            "score": v.score,
            "reasons": v.reasons,
            "explanation": v.explanation,
            "posted": False,
        }

        # 3. only ASK_BADGE reaches the bridge/badge; REJECT/ASK_DELIVERY are logged
        if v.verdict != "ASK_BADGE":
            return result

        beneficiary = raw["beneficiary"]
        if not (beneficiary.startswith("0x") and len(beneficiary) == 42):
            result["verdict"] = "REJECT"
            result["explanation"] += " Beneficiary is not an EVM address (cannot pay on-chain)."
            return result

        req_nonce = nonce if nonce is not None else (int(quote_hash, 16) % (2**31))
        proposal = {
            "supplier_id": raw["supplier_name"][:128] or "unknown",
            "beneficiary": beneficiary,
            "token": token,
            "amount": int(raw["amount"]),
            "deadline": deadline,
            "quote_hash": quote_hash,
            "verdict": "ASK_BADGE",
            "nonce": req_nonce,
            "criteria": v.reasons,
            "flags": v.flags,
            "policy": self.guard.policy["version"],
        }
        try:
            r = requests.post(f"{self.bridge_url}/proposals", json=proposal, timeout=10)
            result["posted"] = r.ok
            result["bridge_response"] = r.json() if r.content else {}
            result["http_status"] = r.status_code
        except Exception as e:
            result["posted"] = False
            result["bridge_error"] = str(e)
        return result
