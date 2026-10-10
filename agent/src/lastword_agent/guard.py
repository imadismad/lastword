"""Guard: apply the pre-validation criteria (section 6, C1-C14), score, verdict.

Rules first (deterministic), model only for ambiguous cases (not needed in the local
path). The guard can only RESTRICT: its verdicts are REJECT, ASK_DELIVERY, ASK_BADGE.
A REJECT is produced if any HARD criterion fails. Otherwise every request that passes
hard criteria goes ASK_DELIVERY then ASK_BADGE (the demo default; level 0 is off).

The flags bits (I1) carry the verdict reasons the badge displays. Hard on-chain
criteria (C1,C3,C6,C8,C9) are RE-checked by the contract; the guard's job is to catch
them early and to carry the off-chain signals (C11-C13) that only the agent can judge.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from lastword_proto import Flag, Role

# Default policy thresholds (versioned; to be set with mentors - placeholders here).
DEFAULT_POLICY = {
    "version": 1,
    "per_tx_cap": 1_000_000_000,       # smallest unit (e.g. 1000 at 6 decimals)
    "daily_cap": 5_000_000_000,
    "allowed_currencies": {"USDC", "dUSD", "USD"},
    "min_supplier_age_ok": True,       # the contract enforces the real timelock (C2)
}

HARD = {"C1", "C3", "C6", "C8", "C9"}


@dataclass
class Verdict:
    verdict: str                       # REJECT | ASK_DELIVERY | ASK_BADGE
    score: float
    reasons: dict = field(default_factory=dict)   # criterion -> pass/fail/na
    flags: int = 0
    explanation: str = ""


class Guard:
    def __init__(self, policy: dict | None = None, whitelist: dict | None = None,
                 seen_quote_hashes: set | None = None):
        self.policy = policy or dict(DEFAULT_POLICY)
        # whitelist: supplier_name -> {"beneficiary","cap","active","age_ok"}
        self.whitelist = whitelist or {}
        self.seen = seen_quote_hashes if seen_quote_hashes is not None else set()

    def evaluate(self, reader_out: dict, quote_hash: str) -> Verdict:
        rs = reader_out.get("risk_signals", {})
        supplier = reader_out.get("supplier_name", "")
        beneficiary = (reader_out.get("beneficiary") or "").lower()
        amount = int(reader_out.get("amount") or 0)
        currency = reader_out.get("currency", "")

        wl = self.whitelist.get(supplier, {})
        reasons: dict[str, str] = {}

        # ----- hard criteria -----
        # C1 supplier whitelisted & active, beneficiary matches the whitelisted address
        c1_ok = bool(wl.get("active")) and (
            not wl.get("beneficiary") or wl["beneficiary"].lower() == beneficiary)
        reasons["C1"] = "pass" if c1_ok else "fail"
        # C3 per-transaction cap
        cap = wl.get("cap", self.policy["per_tx_cap"])
        c3_ok = amount <= cap and amount > 0
        reasons["C3"] = "pass" if c3_ok else "fail"
        # C6 duplicate quote
        c6_ok = quote_hash not in self.seen
        reasons["C6"] = "pass" if c6_ok else "fail"
        # C8 validity (we cannot fully judge expiry here; contract enforces deadline)
        reasons["C8"] = "pass"
        # C9 allowed token/currency
        c9_ok = currency in self.policy["allowed_currencies"]
        reasons["C9"] = "pass" if c9_ok else "fail"

        # ----- off-chain, agent-only criteria -----
        # C11 sender/known (approximated by whitelist membership here)
        reasons["C11"] = "pass" if supplier in self.whitelist else "warn"
        # C12 injection
        injection = bool(rs.get("injection_suspected"))
        reasons["C12"] = "fail" if injection else "pass"
        # C13 anomaly (price/habit) - heuristic: amount near/over cap, or address changed
        anomaly = rs.get("address_changed") or amount >= cap * 0.9 if cap else False
        reasons["C13"] = "warn" if anomaly else "pass"
        # C14 provenance: external or new beneficiary -> badge required (indicator)
        provenance_badge = bool(rs.get("external_origin") or rs.get("new_beneficiary"))

        # ----- score (0..1), higher = riskier -----
        score = 0.0
        score += 0.35 if injection else 0.0
        score += 0.20 if rs.get("address_changed") else 0.0
        score += 0.15 if rs.get("new_beneficiary") else 0.0
        score += 0.10 if rs.get("urgency_pressure") else 0.0
        score += 0.10 if anomaly else 0.0
        score += 0.10 if not c1_ok else 0.0
        score = round(min(score, 1.0), 2)

        # ----- flags (reasons the badge shows) -----
        flags = int(Role.DAF)
        if rs.get("new_beneficiary"):
            flags |= int(Flag.NEW_BENEFICIARY)
        if rs.get("external_origin"):
            flags |= int(Flag.EXTERNAL_ORIGIN)
        if anomaly:
            flags |= int(Flag.ATYPICAL_AMOUNT)
        if injection:
            flags |= int(Flag.INJECTION_SUSPECTED)
        if rs.get("address_changed"):
            flags |= int(Flag.ADDRESS_CHANGED)

        # ----- verdict -----
        hard_fail = [c for c in HARD if reasons.get(c) == "fail"]
        if hard_fail:
            verdict = "REJECT"
            expl = f"Hard criterion failed: {', '.join(sorted(hard_fail))}."
        else:
            # passes hard criteria -> ASK_DELIVERY then ASK_BADGE (demo default)
            verdict = "ASK_BADGE"
            expl = ("Passed hard criteria; requires delivery attestation then a hardware "
                    "badge approval. ")
            if provenance_badge:
                expl += "Badge required by provenance (external/new beneficiary). "
            if injection:
                expl += "A hidden instruction was detected in the quote and flagged (not executed). "

        return Verdict(verdict=verdict, score=score, reasons=reasons, flags=flags,
                       explanation=expl.strip())
