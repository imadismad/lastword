"""I4 local API. Listens only on the configured host (the Dell's WSL/loopback iface).

Accepts a strict proposal (typed, bounded; unknown fields rejected). Never accepts free
text or Meshtastic commands. Returns only statuses to the agent - never raw frames,
keys or radio data.
"""
from __future__ import annotations

import threading

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from lastword_proto import Intent, Role, Flag

from .flow import Flow, Proposal, Status


class ProposalIn(BaseModel):
    model_config = {"extra": "forbid"}  # reject unknown fields

    supplier_id: str = Field(min_length=1, max_length=128)
    beneficiary: str = Field(pattern=r"^0x[0-9a-fA-F]{40}$")
    token: int = Field(ge=0, le=255)
    amount: int = Field(ge=0, lt=2**64)
    deadline: int = Field(ge=0, lt=2**32)
    quote_hash: str = Field(pattern=r"^0x[0-9a-fA-F]{64}$")
    verdict: str
    nonce: int = Field(ge=0, lt=2**32)
    criteria: dict = Field(default_factory=dict)
    flags: int = Field(default=0, ge=0, lt=2**16)
    policy: int = Field(default=1, ge=0, lt=2**16)

    @field_validator("verdict")
    @classmethod
    def _verdict(cls, v):
        if v not in ("REJECT", "ASK_DELIVERY", "ASK_BADGE"):
            raise ValueError("verdict must be REJECT|ASK_DELIVERY|ASK_BADGE")
        return v


def create_app(flow: Flow) -> FastAPI:
    app = FastAPI(title="LASTWORD bridge", version="1.0.0")

    @app.get("/health")
    def health():
        return {"ok": True, "gateway_pub": flow.gateway.public_hex()}

    @app.post("/proposals")
    def post_proposal(body: ProposalIn):
        if body.verdict != "ASK_BADGE":
            # the bridge only forwards ASK_BADGE to the badge; others are logged/refused
            flow.journal.append("VERDICT", "garde", 0,
                                 {"verdict": body.verdict, "supplier": body.supplier_id})
            raise HTTPException(status_code=422,
                                detail=f"verdict {body.verdict} does not reach the badge")

        reqId = body.nonce  # for the PoC we key reqId on the approver nonce
        intent = Intent(
            reqId=reqId,
            beneficiary=bytes.fromhex(body.beneficiary[2:]),
            token=body.token,
            amount=body.amount,
            nonce=body.nonce,
            deadline=body.deadline,
            quoteHash=bytes.fromhex(body.quote_hash[2:]),
            flags=(body.flags & ~0b11) | int(Role.DAF),
            policy=body.policy,
        )
        p = Proposal(reqId=reqId, intent=intent)
        flow.proposals[reqId] = p
        # run the flow in a background thread so the API returns immediately
        threading.Thread(target=flow.run, args=(p,), daemon=True).start()
        return {"reqId": reqId, "status": p.status.value}

    @app.get("/proposals/{reqId}")
    def get_proposal(reqId: int):
        p = flow.proposals.get(reqId)
        if p is None:
            raise HTTPException(status_code=404, detail="unknown reqId")
        # ONLY status is returned to the agent (plus tx hashes for the dashboard)
        return {"reqId": reqId, "status": p.status.value, "detail": p.detail, "tx": p.tx}

    return app
