"""The bridge flow / state machine.

propose(DAF intent) -> badge signs STOCK intent -> attestDelivery(stockIntent, r,s)
                    -> badge signs DAF intent   -> approve(dafIntent, r,s) -> paid.

Model: there are two role-stamped intents that share the economic fields (beneficiary,
token, amount, quoteHash) but differ in the role bits (and nonce). The contract
recomputes each digest from the intent it is given; role separation is enforced by
WHICH key signs (a stock-key sig fails under the DAF pubkey and vice-versa).

Each step is journaled. Badge signatures are s-normalized before chain submit.
Only statuses are ever exposed to the agent.
"""
from __future__ import annotations

import copy
import threading
from dataclasses import dataclass, field
from enum import Enum

from lastword_proto import (
    Intent, Role, digest as compute_digest,
    build_request_frame, open_frame, parse_response_body, normalize_s,
    Command,
)
from lastword_proto.crypto import sig_from_bytes

from .chain import ChainClient
from .gatewaykey import GatewayKey
from .journal import Journal
from .transport import TransportError


class Status(str, Enum):
    RECEIVED = "received"
    PROPOSED = "proposed"
    SENT_STOCK = "sent_stock"
    ATTESTED = "attested"
    SENT_DAF = "sent_daf"
    APPROVED = "approved"
    REFUSED = "refused"
    EXPIRED = "expired"
    ERROR = "error"


@dataclass
class Proposal:
    reqId: int
    intent: Intent                 # the DAF intent (role bits = DAF)
    status: Status = Status.RECEIVED
    detail: str = ""
    tx: dict = field(default_factory=dict)


class Flow:
    def __init__(self, chain: ChainClient, gateway: GatewayKey, journal: Journal,
                 transport, frame_key: bytes, badge_id: int,
                 contract_addr_bytes: bytes, chain_id: int):
        self.chain = chain
        self.gateway = gateway
        self.journal = journal
        self.transport = transport
        self.frame_key = frame_key
        self.badge_id = badge_id
        self.contract_addr = contract_addr_bytes
        self.chain_id = chain_id
        self._counter = 1
        self._lock = threading.Lock()
        self.proposals: dict[int, Proposal] = {}

    def _next_counter(self) -> int:
        with self._lock:
            self._counter += 1
            return self._counter

    def _badge_sign(self, intent: Intent) -> tuple[bytes, bytes] | None:
        """Send one intent to the badge; return (r_bytes32, s_bytes32) or None if refused."""
        dg = compute_digest(intent, self.chain_id, self.contract_addr)
        gateway_sig = self.gateway.sign(dg)
        frame = build_request_frame(self.frame_key, self.badge_id,
                                    self._next_counter(), intent.encode(), gateway_sig)
        cmd, data = self.transport.exchange(Command.REQUEST, frame)
        if cmd == Command.REFUSED:
            reason = data[0] if data else 0xFF
            raise TransportError(f"badge refused: reason 0x{reason:02x}")
        if cmd != Command.RESPONSE:
            raise TransportError(f"unexpected badge reply cmd 0x{cmd:02x}")
        _hdr, pt = open_frame(self.frame_key, data)
        _reqId, decision, badge_sig = parse_response_body(pt)
        if decision != 1:
            return None
        r, s = sig_from_bytes(badge_sig)
        s = normalize_s(s)
        return r.to_bytes(32, "big"), s.to_bytes(32, "big")

    def run(self, p: Proposal):
        try:
            daf_intent = _as_role(p.intent, Role.DAF)
            stock_intent = _as_role(p.intent, Role.STOCK)

            # STEP 1: propose the DAF intent on-chain (stores its digest + runs C1,C3,C6,C8,C9)
            rc = self.chain.propose(daf_intent.encode())
            p.status = Status.PROPOSED
            p.tx["propose"] = rc.transactionHash.hex()
            self.journal.append("VERDICT", "garde", p.reqId,
                                 {"verdict": "ASK_BADGE",
                                  "beneficiary": "0x" + p.intent.beneficiary.hex(),
                                  "amount": p.intent.amount})

            # STEP 2: badge signs the STOCK intent -> attestDelivery
            p.status = Status.SENT_STOCK
            ssig = self._badge_sign(stock_intent)
            if ssig is None:
                return self._refuse(p, "stock attestation refused at badge")
            rc = self.chain.attest(p.reqId, stock_intent.encode(), *ssig)
            p.status = Status.ATTESTED
            p.tx["attest"] = rc.transactionHash.hex()
            self.journal.append("LIVRAISON", "demandeur", p.reqId, {"attested": True})

            # STEP 3: badge signs the DAF intent -> approve -> payment
            p.status = Status.SENT_DAF
            dsig = self._badge_sign(daf_intent)
            if dsig is None:
                return self._refuse(p, "DAF approval refused at badge")
            rc = self.chain.approve(p.reqId, daf_intent.encode(), *dsig)
            p.status = Status.APPROVED
            p.tx["approve"] = rc.transactionHash.hex()
            self.journal.append("APPROBATION", "daf", p.reqId, {"approved": True})
            self.journal.append("EXECUTION", "pont", p.reqId, {"amount": p.intent.amount})
        except TransportError as e:
            self._refuse(p, str(e))
        except Exception as e:
            p.status = Status.ERROR
            p.detail = f"{type(e).__name__}: {e}"
            self.journal.append("REJET", "pont", p.reqId, {"error": p.detail})

    def _refuse(self, p: Proposal, msg: str):
        p.status = Status.REFUSED
        p.detail = msg
        self.journal.append("REJET", "pont", p.reqId, {"reason": msg})


def _as_role(intent: Intent, role: Role) -> Intent:
    c = copy.deepcopy(intent)
    c.with_role(role)
    return c
