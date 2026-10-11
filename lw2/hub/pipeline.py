"""Payment pipeline: agent (read + guard) -> contract propose -> STOCK over LoRa ->
attestDelivery -> role-separation check -> DAF over LoRa -> approve & pay.

Reuses the frozen pieces of v1 (lastword_proto, lastword_agent, lastword_bridge.Flow,
ChainClient, Journal) and instruments every step so the UI can show it live."""
from __future__ import annotations

import hashlib
import os
import threading
import time

import jsonschema
from web3 import Web3

from lastword_agent.guard import Guard, DEFAULT_POLICY
from lastword_agent.reader import LocalReader, make_reader
from lastword_agent.schema import READER_SCHEMA
from lastword_bridge.chain import ChainClient
from lastword_bridge.flow import Flow, Proposal, Status, _as_role
from lastword_bridge.gatewaykey import GatewayKey
from lastword_bridge.journal import Journal
from lastword_bridge.main import provision_badge, _frame_key
from lastword_bridge.transport import TransportError
from lastword_proto import (Intent, Role, Command, digest as compute_digest,
                            build_request_frame, open_frame, parse_response_body, normalize_s)
from lastword_proto.crypto import sig_from_bytes

from .events import BUS
from .radio import MeshRadio, RadioTransport, RadioError

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APPROVE_S = float(os.environ.get("LW_APPROVE_S", "135"))   # station gives the human 120 s
EXPLORER = os.environ.get("LW_EXPLORER_URL", "http://127.0.0.1:3000").rstrip("/")
REFUSE_REASONS = {0x01: "bad gateway signature", 0x02: "bad AEAD / counter (replay or tamper)",
                  0x03: "refused by the human", 0x04: "expired", 0x05: "not provisioned",
                  0xFF: "other"}


def _tx(rc) -> str:
    h = rc.transactionHash.hex()
    return h if h.startswith("0x") else "0x" + h


# ======================================================================== agent
class Agent:
    """Isolated reader (no tools, strict JSON schema) + deterministic guard (C1..C14)."""
    def __init__(self):
        import json
        self.policy = dict(DEFAULT_POLICY)
        wl = os.environ.get("LW_WHITELIST", os.path.join(ROOT, "agent", "demo", "whitelist.json"))
        self.whitelist = json.load(open(wl))
        self.reader_mode = os.environ.get("LW_READER", "local")

    def reader(self):
        if self.reader_mode == "bedrock" and os.environ.get("BEDROCK_MODEL_ID"):
            return make_reader(prefer_bedrock=True, model_id=os.environ["BEDROCK_MODEL_ID"],
                               region=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
        return LocalReader()

    def evaluate(self, text: str, deadline_mins: int = 15, token: int = 0) -> dict:
        t0 = time.time()
        quote_hash = "0x" + hashlib.sha256(text.encode()).hexdigest()
        pol = dict(self.policy)
        pol["allowed_currencies"] = set(pol.get("allowed_currencies", []))
        guard = Guard(policy=pol, whitelist=self.whitelist)
        reader = self.reader()
        raw = reader.read(text, known_suppliers=dict(self.whitelist))
        schema_ok, schema_err = True, None
        try:
            jsonschema.validate(raw, READER_SCHEMA)
        except jsonschema.ValidationError as e:
            schema_ok, schema_err = False, e.message
        v = guard.evaluate(raw, quote_hash)
        beneficiary = raw.get("beneficiary") or ""
        evm_ok = beneficiary.startswith("0x") and len(beneficiary) == 42
        proposal = None
        if v.verdict == "ASK_BADGE" and evm_ok and schema_ok:
            proposal = {
                "supplier": (raw.get("supplier_name") or "unknown")[:128],
                "beneficiary": beneficiary, "token": token,
                "amount": int(raw.get("amount") or 0),
                "deadline": int(time.time()) + deadline_mins * 60,
                "quote_hash": quote_hash, "nonce": int(quote_hash, 16) % (2 ** 31),
                "flags": v.flags, "policy": self.policy.get("version", 1),
            }
        out = {"reader": reader.name, "quote_hash": quote_hash, "schema_ok": schema_ok,
               "schema_error": schema_err, "extracted": raw, "verdict": v.verdict,
               "score": v.score, "reasons": v.reasons, "flags": v.flags,
               "explanation": v.explanation, "proposal": proposal,
               "ms": round((time.time() - t0) * 1000)}
        BUS.emit("agent.verdict", verdict=v.verdict, score=v.score,
                 supplier=raw.get("supplier_name"), amount=raw.get("amount"),
                 injection=bool((raw.get("risk_signals") or {}).get("injection_suspected")))
        return out


# ======================================================================== flow
class LiveFlow(Flow):
    """lastword_bridge.Flow with every step published, the last frames kept for the
    replay/tamper attacks, and a role-separation check between attest and approve."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.last_request_frame: bytes | None = None
        self.payments: dict[int, dict] = {}

    def _step(self, p: Proposal, step: str, state: str, **extra):
        rec = self.payments.setdefault(p.reqId, {"reqId": p.reqId, "steps": {}, "t0": time.time()})
        s = rec["steps"].setdefault(step, {})
        now = time.time()
        if state == "active":
            s["t0"] = now
        elif "t0" in s:
            s["ms"] = round((now - s["t0"]) * 1000)
        s.update(state=state, **extra)
        BUS.emit("pay.step", reqId=p.reqId, step=step, state=state,
                 ms=s.get("ms"), **extra)

    def _badge_sign(self, intent: Intent, label: str = "") -> tuple[bytes, bytes] | None:
        dg = compute_digest(intent, self.chain_id, self.contract_addr)
        frame = build_request_frame(self.frame_key, self.badge_id, self._next_counter(),
                                    intent.encode(), self.gateway.sign(dg))
        self.last_request_frame = frame
        self.transport.label = label
        cmd, data = self.transport.exchange(Command.REQUEST, frame)
        if cmd == Command.REFUSED:
            reason = data[0] if data else 0xFF
            raise TransportError(f"badge refused: {REFUSE_REASONS.get(reason, hex(reason))}")
        if cmd != Command.RESPONSE:
            raise TransportError(f"unexpected badge reply 0x{cmd:02x}")
        _hdr, pt = open_frame(self.frame_key, data)
        _reqId, decision, badge_sig = parse_response_body(pt)
        if decision != 1:
            return None
        r, s = sig_from_bytes(badge_sig)
        return r.to_bytes(32, "big"), normalize_s(s).to_bytes(32, "big")

    def run(self, p: Proposal):
        cur = "propose"
        try:
            daf_intent = _as_role(p.intent, Role.DAF)
            stock_intent = _as_role(p.intent, Role.STOCK)

            self._step(p, "propose", "active")
            rc = self.chain.propose(daf_intent.encode())
            p.status, p.tx["propose"] = Status.PROPOSED, _tx(rc)
            self._step(p, "propose", "done", tx=p.tx["propose"])
            self.journal.append("VERDICT", "garde", p.reqId,
                                {"verdict": "ASK_BADGE", "beneficiary": "0x" + p.intent.beneficiary.hex(),
                                 "amount": p.intent.amount})

            cur = "stock"
            self._step(p, "stock", "active", role="STOCK")
            p.status = Status.SENT_STOCK
            ssig = self._badge_sign(stock_intent, "STOCK")
            if ssig is None:
                self._step(p, "stock", "error", detail="the human refused (N) on the badge")
                return self._refuse(p, "stock attestation refused at badge")
            self._step(p, "stock", "done")

            cur = "attest"
            self._step(p, "attest", "active")
            rc = self.chain.attest(p.reqId, stock_intent.encode(), *ssig)
            p.status, p.tx["attest"] = Status.ATTESTED, _tx(rc)
            self._step(p, "attest", "done", tx=p.tx["attest"])
            self.journal.append("LIVRAISON", "demandeur", p.reqId, {"attested": True})

            cur = "rolecheck"
            self._step(p, "rolecheck", "active")
            self._role_check(p, daf_intent, ssig)

            cur = "daf"
            self._step(p, "daf", "active", role="DAF")
            p.status = Status.SENT_DAF
            dsig = self._badge_sign(daf_intent, "DAF")
            if dsig is None:
                self._step(p, "daf", "error", detail="the human refused (N) on the badge")
                return self._refuse(p, "DAF approval refused at badge")
            self._step(p, "daf", "done")

            cur = "approve"
            self._step(p, "approve", "active")
            rc = self.chain.approve(p.reqId, daf_intent.encode(), *dsig)
            p.status, p.tx["approve"] = Status.APPROVED, _tx(rc)
            self._step(p, "approve", "done", tx=p.tx["approve"])
            self.journal.append("APPROBATION", "daf", p.reqId, {"approved": True})
            self.journal.append("EXECUTION", "pont", p.reqId, {"amount": p.intent.amount})
            total = time.time() - self.payments[p.reqId]["t0"]
            BUS.emit("pay.done", reqId=p.reqId, status="paid", total_ms=round(total * 1000),
                     tx=p.tx, amount=p.intent.amount)
        except TransportError as e:
            self._step(p, cur, "error", detail=str(e))
            self._refuse(p, str(e))
            BUS.emit("pay.done", reqId=p.reqId, status="refused", detail=str(e), tx=p.tx)
        except Exception as e:
            p.status, p.detail = Status.ERROR, f"{type(e).__name__}: {e}"
            self._step(p, cur, "error", detail=p.detail)
            self.journal.append("REJET", "pont", p.reqId, {"error": p.detail})
            BUS.emit("pay.done", reqId=p.reqId, status="error", detail=p.detail, tx=p.tx)

    def _role_check(self, p: Proposal, daf_intent: Intent, stock_sig):
        """Attack #3 of the spec, run on every payment: present the STOCK signature as a
        DAF approval (eth_call, nothing is sent). The contract must revert."""
        try:
            self.chain.contract.functions.approve(p.reqId, daf_intent.encode(), *stock_sig).call(
                {"from": self.chain.acct.address})
            self._step(p, "rolecheck", "error", detail="contract ACCEPTED a stock signature as DAF")
            raise RuntimeError("role separation broken: stock signature accepted as DAF")
        except RuntimeError:
            raise
        except Exception as e:
            self._step(p, "rolecheck", "done",
                       detail="stock signature presented as DAF -> reverted by the contract",
                       revert=type(e).__name__)


# ======================================================================== hub core
class Core:
    def __init__(self, gateway_port: str):
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, ".env"))
        self.agent = Agent()
        self.radio = MeshRadio(gateway_port, "gateway")
        self.chain = ChainClient(os.environ["LASTWORD_RPC_URL"], os.environ["LASTWORD_CONTRACT_ADDRESS"],
                                 os.environ["BRIDGE_PRIVATE_KEY"],
                                 agent_private_key=os.environ.get("AGENT_PRIVATE_KEY"))
        self.contract_addr = os.environ["LASTWORD_CONTRACT_ADDRESS"]
        self.gateway = (GatewayKey.from_seed(os.environ["GATEWAY_SEED"].encode())
                        if os.environ.get("GATEWAY_SEED") else GatewayKey.from_seed())
        os.makedirs(os.path.join(ROOT, "lw2", "data"), exist_ok=True)
        self.journal_path = os.path.join(ROOT, "lw2", "data", "journal.jsonl")
        self.journal = Journal(self.journal_path)
        self.transport = RadioTransport(self.radio, APPROVE_S)
        self.flow = LiveFlow(self.chain, self.gateway, self.journal, self.transport, _frame_key(),
                             int(os.environ.get("BADGE_ID", "40961")),
                             bytes.fromhex(Web3.to_checksum_address(self.contract_addr)[2:]),
                             self.chain.chain_id, transport_spec="mesh:" + gateway_port)
        self.badge = {"provisioned": False, "pubkeys": None, "keys_match_contract": None}
        self._plock = threading.Lock()

    def start(self):
        self.radio.open()
        threading.Thread(target=self._provision_loop, daemon=True).start()

    # ---- badge provisioning over LoRa (HELLO + PROVISION) --------------------
    def provision(self) -> dict:
        with self._plock:
            BUS.emit("badge.provisioning")
            self.transport.label = "PROVISION"
            pk = provision_badge(self.transport, self.flow.frame_key, self.chain.chain_id,
                                 self.flow.contract_addr, self.gateway.public_bytes())
            self.flow.pubkeys = pk
            match = self._keys_match(pk)
            self.badge.update(provisioned=True, pubkeys=pk, keys_match_contract=match,
                              at=time.time())
            BUS.emit("badge.provisioned", stock=pk["stock"][:16], daf=pk["daf"][:16],
                     keys_match_contract=match)
            return self.badge

    def _keys_match(self, pk: dict) -> bool | None:
        try:
            c = self.chain.w3.eth.contract(address=self.chain.contract.address, abi=[
                {"type": "function", "name": n, "stateMutability": "view", "inputs": [],
                 "outputs": [{"name": "", "type": "bytes32"}]} for n in ("stockQx", "dafQx")])
            return (c.functions.stockQx().call().hex().removeprefix("0x") == pk["stock"][:64]
                    and c.functions.dafQx().call().hex().removeprefix("0x") == pk["daf"][:64])
        except Exception:
            return None

    station_ready = staticmethod(lambda: True)   # set by the app: station heartbeat is fresh

    def _provision_loop(self):
        while not self.badge["provisioned"]:
            if not self.station_ready():
                time.sleep(2)   # the station is still warming the badge / opening nugget-3
                continue
            try:
                self.provision()
            except Exception as e:
                BUS.emit("badge.provision_failed", detail=str(e)[:200])
                time.sleep(10)

    # ---- payments -------------------------------------------------------------
    def pay(self, prop: dict) -> int:
        if not self.badge["provisioned"]:
            raise RuntimeError("badge not provisioned over LoRa yet")
        reqId = int(prop["nonce"])
        if reqId in self.flow.proposals:
            raise RuntimeError("this quote was already submitted (duplicate guard C6)")
        intent = Intent(reqId=reqId, beneficiary=bytes.fromhex(prop["beneficiary"][2:]),
                        token=int(prop["token"]), amount=int(prop["amount"]), nonce=reqId,
                        deadline=int(prop["deadline"]), quoteHash=bytes.fromhex(prop["quote_hash"][2:]),
                        flags=(int(prop.get("flags", 0)) & ~0b11) | int(Role.DAF),
                        policy=int(prop.get("policy", 1)))
        p = Proposal(reqId=reqId, intent=intent)
        self.flow.proposals[reqId] = p
        BUS.emit("pay.start", reqId=reqId, supplier=prop.get("supplier"),
                 beneficiary=prop["beneficiary"], amount=intent.amount)
        threading.Thread(target=self.flow.run, args=(p,), daemon=True).start()
        return reqId

    # ---- live attacks (spec 16 bis) -------------------------------------------
    def attack(self, kind: str) -> dict:
        frame = self.flow.last_request_frame
        if kind in ("replay", "tamper"):
            if frame is None:
                raise RuntimeError("run one payment first: there is no captured frame yet")
            if kind == "tamper":
                b = bytearray(frame)
                b[len(b) // 2] ^= 0x01          # one bit, in the sealed ciphertext
                frame = bytes(b)
            BUS.emit("attack.start", kind=kind, size=len(frame))
            self.transport.label = "ATTACK " + kind.upper()
            try:
                cmd, data = self.radio.exchange(Command.REQUEST, frame, timeout=30, label=kind)
            except RadioError as e:
                res = {"kind": kind, "blocked": True, "by": "badge (silent drop)", "detail": str(e)}
            else:
                if cmd == Command.REFUSED:
                    reason = REFUSE_REASONS.get(data[0] if data else 0xFF)
                    res = {"kind": kind, "blocked": True, "by": "badge", "detail": f"REFUSED: {reason}"}
                else:
                    res = {"kind": kind, "blocked": False, "by": None,
                           "detail": f"badge answered 0x{cmd:02x} — check the e-paper"}
            BUS.emit("attack.result", **res)
            return res
        raise ValueError(f"unknown attack {kind}")

    def tx_url(self, h: str) -> str:
        return f"{EXPLORER}/tx/{h}"
