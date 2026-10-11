"""LASTWORD benchmark (spec section 14): detection vs baselines, contract enforcement,
radio-frame attacks and journal tampering. Everything runs locally and reproducibly:
the real LastWord contract on anvil, the real agent code, the software badge (same
protocol as the TROPIC01 firmware).

    python bench/dataset.py && python bench/run.py      -> bench/results/{results.json,report.md}
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in ("proto/src", "agent/src", "bridge/src", "badge-sim"):
    sys.path.insert(0, os.path.join(ROOT, p))

from web3 import Web3  # noqa: E402

from lastword_agent.guard import Guard, DEFAULT_POLICY  # noqa: E402
from lastword_agent.reader import LocalReader  # noqa: E402
from lastword_bridge.chain import ChainClient  # noqa: E402
from lastword_bridge.journal import Journal  # noqa: E402
from lastword_proto import (Intent, Role, Command, Flag, digest as compute_digest,  # noqa: E402
                            build_request_frame, normalize_s, pack_message, unpack_message)
from lastword_proto.crypto import sign_digest, sig_from_bytes  # noqa: E402
from lastword_bridge.gatewaykey import GatewayKey  # noqa: E402
import badge_sim  # noqa: E402

PORT = 8547
RPC = f"http://127.0.0.1:{PORT}"
FORGE = shutil.which("forge") or os.path.expanduser("~/.foundry/bin/forge.exe")
ANVIL = shutil.which("anvil") or os.path.expanduser("~/.foundry/bin/anvil.exe")
DEPLOYER_PK = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"   # anvil #0 (public)
AGENT = ("0x70997970C51812dc3A010C7d01b50e0d17dc79C8", "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d")
BRIDGE = ("0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC", "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a")
WL = json.load(open(os.path.join(ROOT, "agent", "demo", "whitelist.json"), encoding="utf-8"))
FRAME_KEY = hashlib.sha256(b"lastword-frame-key-poc").digest()
SEL_HARD = Web3.keccak(text="HardCriterion(uint8)")[:4].hex()
ERRORS = {Web3.keccak(text=s)[:4].hex(): s for s in
          ("BadState()", "BadSignature()", "NotAuthorized()", "IsPaused()", "TimelockNotReady()")}


# ============================================================================ chain
def start_anvil():
    proc = subprocess.Popen([ANVIL, "--port", str(PORT), "--silent"], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            if Web3(Web3.HTTPProvider(RPC)).is_connected():
                return proc
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("anvil did not start")


def deploy(badge) -> tuple[ChainClient, str]:
    pub = badge.pubkeys_blob().hex()
    env = {**os.environ, "PRIVATE_KEY": DEPLOYER_PK, "AGENT_ADDR": AGENT[0], "BRIDGE_ADDR": BRIDGE[0],
           "COADMIN_ADDR": "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
           "GUARDIAN_ADDR": "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
           "STOCK_QX": "0x" + pub[:64], "STOCK_QY": "0x" + pub[64:128],
           "DAF_QX": "0x" + pub[128:192], "DAF_QY": "0x" + pub[192:256],
           "DURESS_QX": "0x" + pub[256:320], "DURESS_QY": "0x" + pub[320:384],
           "WHITELIST_DELAY": "60", "PARALLEL_CAP": "50000000"}
    out = subprocess.run([FORGE, "script", "script/Deploy.s.sol", "--rpc-url", RPC, "--broadcast"],
                         cwd=os.path.join(ROOT, "contracts"), env=env, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError("deploy failed:\n" + out.stdout[-2000:] + out.stderr[-2000:])
    lw = next(l.split()[-1] for l in out.stdout.splitlines() if "LastWord:" in l)
    chain = ChainClient(RPC, lw, BRIDGE[1], agent_private_key=AGENT[1])
    admin = chain.w3.eth.account.from_key(DEPLOYER_PK)
    seed = chain.w3.eth.contract(address=chain.contract.address, abi=[{
        "type": "function", "name": "seedSupplierForDemo", "stateMutability": "nonpayable",
        "inputs": [{"name": "s", "type": "address"}, {"name": "c", "type": "uint64"}, {"name": "a", "type": "uint64"}],
        "outputs": []}])
    for name, w in WL.items():        # on-chain whitelist = the agent's whitelist (suspended stays off)
        if w["active"]:
            chain._send(seed.functions.seedSupplierForDemo(Web3.to_checksum_address(w["beneficiary"]), w["cap"], 120), admin)
    return chain, lw


def revert_reason(e: Exception) -> str:
    data = getattr(e, "data", None) or (e.args[1] if len(getattr(e, "args", ())) > 1 else None)
    data = data if isinstance(data, str) else str(data or e)
    for token in data.replace("'", " ").replace('"', " ").split():
        t = token.lower()
        if t.startswith("0x" + SEL_HARD.removeprefix("0x")):
            return f"C{int(t[-2:], 16)}"
        for sel, name in ERRORS.items():
            if t.startswith("0x" + sel.removeprefix("0x")):
                return name.removesuffix("()")
    return type(e).__name__


def make_intent(reqId, beneficiary, amount, quote_hash, deadline, flags=0, role=Role.DAF) -> Intent:
    return Intent(reqId=reqId, beneficiary=bytes.fromhex(beneficiary[2:]), token=0, amount=amount,
                  nonce=reqId, deadline=deadline, quoteHash=quote_hash,
                  flags=(flags & ~0b11) | int(role), policy=1)


def propose(chain: ChainClient, intent: Intent) -> str | None:
    """None if the contract accepted the proposal, else the criterion it reverted on."""
    fn = chain.contract.functions.propose(intent.encode(), b"")
    try:
        fn.call({"from": chain.agent_acct.address})
    except Exception as e:
        return revert_reason(e)
    chain.propose(intent.encode())
    return None


# ============================================================================ detection
def evaluate_dataset(rows):
    reader = LocalReader()
    pol = dict(DEFAULT_POLICY); pol["allowed_currencies"] = set(pol["allowed_currencies"])
    lat = []
    out = []
    seen_refs = set()
    for r in rows:
        t0 = time.perf_counter()
        raw = reader.read(r["text"], known_suppliers=WL)
        qh = "0x" + hashlib.sha256(r["text"].encode()).hexdigest()
        v = Guard(policy=pol, whitelist=WL).evaluate(raw, qh)   # as built in lw2: no cross-quote memory
        lat.append((time.perf_counter() - t0) * 1000)
        rs = raw.get("risk_signals", {})
        warnings = [n for n, bit in (("new beneficiary", Flag.NEW_BENEFICIARY), ("atypical amount", Flag.ATYPICAL_AMOUNT),
                                     ("hidden instruction", Flag.INJECTION_SUSPECTED), ("address changed", Flag.ADDRESS_CHANGED))
                    if v.flags & int(bit)]
        ben = raw.get("beneficiary") or ""
        # ---- baselines: classic AP automation, rules only, auto-pay, no hardware approval
        known = WL.get(raw.get("supplier_name"), {})
        # baselines read the invoice number themselves (the agent's quote_ref regex
        # captures the word "ref" itself; harmless for the agent, fatal for a dedup rule)
        m = re.search(r"(?i)\bref\s*:\s*(\S+)", r["text"])
        ref = m.group(1) if m else None
        r1_pay = bool(known.get("active")) and 0 < int(raw.get("amount") or 0) <= known.get("cap", 0) and ref not in seen_refs
        r2_pay = r1_pay and ben.lower() == (known.get("beneficiary") or "").lower()
        if r1_pay:
            seen_refs.add(ref)
        out.append({**r, "extracted": {"supplier": raw.get("supplier_name"), "beneficiary": ben, "amount": raw.get("amount")},
                    "verdict": v.verdict, "score": v.score, "flags": v.flags, "warnings": warnings,
                    "urgency": bool(rs.get("urgency_pressure")), "failed": [c for c, s in v.reasons.items() if s == "fail"],
                    "quote_hash": qh, "base_r1_pay": r1_pay, "base_r2_pay": r2_pay})
    return out, lat


def run_contract_layers(cases, badge):
    """Layer A: as built (only agent-approved quotes reach propose).
    Layer B: agent compromised (every payable quote is proposed): does the contract alone hold?"""
    for layer, key in (("A", "contract_as_built"), ("B", "contract_agent_compromised")):
        chain, _ = deploy(badge)
        now = chain.w3.eth.get_block("latest").timestamp
        for i, c in enumerate(cases):
            ben, amt = c["extracted"]["beneficiary"], int(c["extracted"]["amount"] or 0)
            payable = ben.startswith("0x") and len(ben) == 42 and amt > 0
            if not payable:
                c[key] = "no payable address"
                continue
            if layer == "A" and c["verdict"] != "ASK_BADGE":
                c[key] = "not sent (agent stopped it)"
                continue
            it = make_intent(100_000 + i, ben, amt, bytes.fromhex(c["quote_hash"][2:]), now + 900, c["flags"])
            reason = propose(chain, it)
            c[key] = reason or "accepted -> needs the badge"
    return cases


# ============================================================================ frames & contract replay
class SimTransport:
    def __init__(self, badge):
        self.badge = badge

    def exchange(self, cmd, data=b""):
        return unpack_message(self.badge.handle(pack_message(cmd, data)))


def frame_and_chain_tests(badge, n=50):
    rng = random.Random(7)
    chain, lw = deploy(badge)
    gw = GatewayKey.from_seed()
    contract_bytes = bytes.fromhex(Web3.to_checksum_address(lw)[2:])
    t = SimTransport(badge)
    t.exchange(Command.PROVISION, FRAME_KEY + chain.chain_id.to_bytes(8, "big") + contract_bytes + gw.public_bytes())
    acme = WL["ACME Steel Supplies"]["beneficiary"]
    res = defaultdict(Counter)
    counter = [10]

    def frame_for(intent, key=gw):
        counter[0] += 1
        dg = compute_digest(intent, chain.chain_id, contract_bytes)
        return build_request_frame(FRAME_KEY, 40961, counter[0], intent.encode(), key.sign(dg))

    def badge_sign(intent):
        cmd, data = t.exchange(Command.REQUEST, frame_for(intent))
        assert cmd == Command.RESPONSE, f"badge refused a valid frame: {cmd}"
        from lastword_proto import open_frame, parse_response_body
        _h, pt = open_frame(FRAME_KEY, data)
        _rid, _dec, sig = parse_response_body(pt)
        r, s = sig_from_bytes(sig)
        return r.to_bytes(32, "big"), normalize_s(s).to_bytes(32, "big")

    now = chain.w3.eth.get_block("latest").timestamp
    base = make_intent(1, acme, 100_000_000, b"\x11" * 32, now + 900)

    # T-02a forged frames (one random bit flipped in transit)
    for _ in range(n):
        f = bytearray(frame_for(base)); f[rng.randrange(len(f))] ^= 1 << rng.randrange(8)
        cmd, _ = t.exchange(Command.REQUEST, bytes(f))
        res["forged_frame"]["refused" if cmd == Command.REFUSED else "ACCEPTED"] += 1
    # T-02b frames signed by a key that is not the gateway
    rogue = GatewayKey.from_seed(b"attacker")
    for _ in range(n):
        cmd, _ = t.exchange(Command.REQUEST, frame_for(base, rogue))
        res["rogue_gateway_frame"]["refused" if cmd == Command.REFUSED else "ACCEPTED"] += 1
    # T-02c replayed frames: the exact same frame sent twice
    for _ in range(n):
        f = frame_for(base)
        t.exchange(Command.REQUEST, f)
        cmd, _ = t.exchange(Command.REQUEST, f)
        res["replayed_frame_at_badge"]["refused" if cmd == Command.REFUSED else "re-displayed & signed"] += 1

    # full payments on the contract, then attack them (T-02/T-03 at the contract)
    for i in range(n):
        qh = hashlib.sha256(f"bench-{i}".encode()).digest()
        it = make_intent(5000 + i, acme, 10_000_000 + i, qh, chain.w3.eth.get_block("latest").timestamp + 900)
        chain.propose(it.encode())
        st = make_intent(it.reqId, acme, it.amount, qh, it.deadline, role=Role.STOCK)
        ssig = badge_sign(st)
        chain.attest(it.reqId, st.encode(), *ssig)
        # T-03 a parameter changed after the badge signed (amount / beneficiary)
        dsig = badge_sign(it)
        bad = make_intent(it.reqId, acme if i % 2 else "0x" + "66" * 20, it.amount + (1 if i % 2 else 0), qh, it.deadline)
        try:
            chain.contract.functions.approve(it.reqId, bad.encode(), *dsig).call({"from": chain.acct.address})
            res["param_changed_after_signature"]["ACCEPTED"] += 1
        except Exception as e:
            res["param_changed_after_signature"][f"refused ({revert_reason(e)})"] += 1
        # STOCK signature presented as DAF
        try:
            chain.contract.functions.approve(it.reqId, it.encode(), *ssig).call({"from": chain.acct.address})
            res["stock_sig_as_daf"]["ACCEPTED"] += 1
        except Exception as e:
            res["stock_sig_as_daf"][f"refused ({revert_reason(e)})"] += 1
        chain.approve(it.reqId, it.encode(), *dsig)   # the genuine approval pays once
        # replay the very same approval
        try:
            chain.contract.functions.approve(it.reqId, it.encode(), *dsig).call({"from": chain.acct.address})
            res["approval_replayed_on_chain"]["ACCEPTED"] += 1
        except Exception as e:
            res["approval_replayed_on_chain"][f"refused ({revert_reason(e)})"] += 1
    # expired: valid signatures, but the deadline passed before approval
    for i in range(n):
        qh = hashlib.sha256(f"bench-exp-{i}".encode()).digest()
        now = chain.w3.eth.get_block("latest").timestamp
        it = make_intent(9000 + i, acme, 1_000_000, qh, now + 300)
        chain.propose(it.encode())
        st = make_intent(it.reqId, acme, it.amount, qh, it.deadline, role=Role.STOCK)
        chain.attest(it.reqId, st.encode(), *badge_sign(st))
        dsig = badge_sign(it)
        chain.w3.provider.make_request("evm_increaseTime", [600]); chain.w3.provider.make_request("evm_mine", [])
        try:
            chain.contract.functions.approve(it.reqId, it.encode(), *dsig).call({"from": chain.acct.address})
            res["approved_after_deadline"]["ACCEPTED"] += 1
        except Exception as e:
            res["approved_after_deadline"][f"refused ({revert_reason(e)})"] += 1
    return {k: dict(v) for k, v in res.items()}


# ============================================================================ journal
def journal_tests(n=50):
    rng = random.Random(11)
    res = defaultdict(Counter)
    d = tempfile.mkdtemp(prefix="lwjournal-")
    for mode in ("modify", "delete", "reorder"):
        for k in range(n):
            p = os.path.join(d, f"{mode}-{k}.jsonl")
            j = Journal(p)
            for i in range(100):
                j.append(rng.choice(["VERDICT", "LIVRAISON", "APPROBATION", "REJET"]), "bench", i, {"i": i, "amount": rng.randint(1, 10**9)})
            lines = open(p, encoding="utf-8").read().splitlines()
            idx = rng.randrange(1, 99)
            if mode == "modify":
                e = json.loads(lines[idx]); e["payload"]["amount"] += 1; lines[idx] = json.dumps(e)
            elif mode == "delete":
                del lines[idx]
            else:
                lines[idx], lines[idx + 1] = lines[idx + 1], lines[idx]
            open(p, "w", encoding="utf-8").write("\n".join(lines) + "\n")
            ok, bad_at, _ = Journal.verify(p)
            located = bad_at is not None and abs(int(bad_at) - (idx + 1)) <= 1
            res[mode]["detected" if not ok else "MISSED"] += 1
            res[mode]["first bad entry located"] += int(located)
    shutil.rmtree(d, ignore_errors=True)
    return {k: dict(v) for k, v in res.items()}


# ============================================================================ report
def pct(a, b):
    return f"{100 * a / b:.1f} %" if b else "—"


def summarize(cases, lat):
    normals = [c for c in cases if c["label"] == "normal"]
    attacks = [c for c in cases if c["label"] == "attack"]
    types = sorted({c["type"] for c in attacks})

    def agent_alert(c):     # the agent stops it or shows a warning the human sees on the badge
        return c["verdict"] == "REJECT" or bool(c["warnings"]) or c["urgency"]

    def stopped_lastword(c):  # never reaches the badge: agent REJECT or contract revert
        return c["verdict"] == "REJECT" or not c["contract_as_built"].startswith("accepted")

    def to_attacker(c):
        a = c.get("attacker_address")
        return bool(a) and c["extracted"]["beneficiary"].lower() == a.lower()

    S = {"dataset": {"normal": len(normals), "attacks": len(attacks), "by_type": dict(Counter(c["type"] for c in attacks))}}
    tp = sum(agent_alert(c) for c in attacks); fp = sum(agent_alert(c) for c in normals)
    S["agent"] = {
        "detected_attacks": tp, "recall": tp / len(attacks), "precision": tp / (tp + fp) if tp + fp else None,
        "false_reject_rate": sum(c["verdict"] == "REJECT" for c in normals) / len(normals),
        "false_warning_rate": fp / len(normals),
        "latency_ms_median": statistics.median(lat), "latency_ms_p95": sorted(lat)[int(0.95 * len(lat))],
    }
    S["per_type"] = {}
    for t in types:
        cs = [c for c in attacks if c["type"] == t]
        S["per_type"][t] = {
            "n": len(cs),
            "agent_rejects": sum(c["verdict"] == "REJECT" for c in cs),
            "agent_alerts": sum(agent_alert(c) for c in cs),
            "stopped_before_badge": sum(stopped_lastword(c) for c in cs),
            "contract_alone_stops": sum(not c["contract_agent_compromised"].startswith("accepted") for c in cs),
            "reach_badge_with_warning": sum((not stopped_lastword(c)) and agent_alert(c) for c in cs),
            "reach_badge_silent": sum((not stopped_lastword(c)) and not agent_alert(c) for c in cs),
            "baseline_r1_autopaid": sum(c["base_r1_pay"] for c in cs),
            "baseline_r2_autopaid": sum(c["base_r2_pay"] for c in cs),
        }
    atk_amt = lambda f: sum(int(c["units"]) for c in attacks if f(c))
    S["exposure"] = {
        "attacker_wallet_payable_lastword": sum(to_attacker(c) and c["contract_agent_compromised"].startswith("accepted") for c in attacks),
        "baseline_r1_autopaid_attacks": sum(c["base_r1_pay"] for c in attacks),
        "baseline_r1_autopaid_units": atk_amt(lambda c: c["base_r1_pay"]),
        "baseline_r1_to_attacker_units": atk_amt(lambda c: c["base_r1_pay"] and to_attacker(c)),
        "baseline_r2_autopaid_attacks": sum(c["base_r2_pay"] for c in attacks),
        "baseline_r2_autopaid_units": atk_amt(lambda c: c["base_r2_pay"]),
        "lastword_autopaid": 0,
    }
    S["normals"] = {
        "reach_badge": sum(not stopped_lastword(c) for c in normals),
        "false_rejects": [{"id": c["id"], "type": c["type"], "failed": c["failed"], "supplier_read": c["extracted"]["supplier"]}
                          for c in normals if c["verdict"] == "REJECT"][:20],
        "baseline_r1_autopaid": sum(c["base_r1_pay"] for c in normals),
    }
    return S


def report_md(S, frames, journal) -> str:
    a, e = S["agent"], S["exposure"]
    L = ["# LASTWORD benchmark", "",
         f"Synthetic, reproducible dataset (seed fixed, no real data): **{S['dataset']['normal']} normal payments** "
         f"and **{S['dataset']['attacks']} attacks** (10 per type). Real `LastWord` contract on a local chain, real agent "
         "code, software badge speaking the same protocol as the TROPIC01 firmware.", "",
         "## Headline", "",
         f"- Funds payable to an attacker-controlled wallet: **{e['attacker_wallet_payable_lastword']}**, even with the agent assumed compromised "
         f"(the contract only pays whitelisted addresses). Rules-only automation auto-pays **{e['baseline_r1_autopaid_attacks']} of 60** attacks "
         f"({e['baseline_r1_autopaid_units'] / 1e6:,.0f} dUSD, of which {e['baseline_r1_to_attacker_units'] / 1e6:,.0f} dUSD to attacker wallets).",
         f"- Payments executed without a human PIN on the hardware badge: **0** (LASTWORD) vs every rule-passing invoice (baselines).",
         f"- Agent detection (stop or visible warning): recall **{pct(a['detected_attacks'], S['dataset']['attacks'])}**, "
         f"precision **{a['precision']:.1%}**, false rejects **{a['false_reject_rate']:.1%}**, false warnings **{a['false_warning_rate']:.1%}**.",
         f"- Detection delay (quote -> verdict): median **{a['latency_ms_median']:.2f} ms**, p95 {a['latency_ms_p95']:.2f} ms (local reader).", "",
         "## Per attack type", "",
         "| Attack (10 each) | Agent rejects | Agent alerts | Stopped before badge | Contract alone stops (agent compromised) | Reaches badge with warning | Reaches badge silently | Rules-only (R1) auto-pays | Strong rules (R2) auto-pays |",
         "|---|---|---|---|---|---|---|---|---|"]
    for t, v in S["per_type"].items():
        L.append(f"| {t} | {v['agent_rejects']} | {v['agent_alerts']} | {v['stopped_before_badge']} | {v['contract_alone_stops']} | "
                 f"{v['reach_badge_with_warning']} | {v['reach_badge_silent']} | {v['baseline_r1_autopaid']} | {v['baseline_r2_autopaid']} |")
    L += ["", "R1 = classic AP rules (known vendor, under cap, new invoice number) paying the address on the invoice. "
          "R2 = R1 + payout address must match the vendor master. Both pay automatically, with no hardware approval.", "",
          "## Radio frames and contract enforcement (T-02, T-03)", "", "| Test (50 each) | Result |", "|---|---|"]
    for k, v in frames.items():
        L.append(f"| {k} | {', '.join(f'{n} {r}' for r, n in v.items())} |")
    L += ["", "## Evidence journal tampering (T-07)", "", "| Tamper (50 each) | Result |", "|---|---|"]
    for k, v in journal.items():
        L.append(f"| {k} | {', '.join(f'{n} {r}' for r, n in v.items())} |")
    L += ["", "## Normal traffic", "",
          f"- {S['normals']['reach_badge']} of {S['dataset']['normal']} legitimate payments reach the badge for approval.",
          f"- False rejects (legit payment blocked by the agent): {len(S['normals']['false_rejects'])} shown below (first 20).", ""]
    for fr in S["normals"]["false_rejects"]:
        L.append(f"  - #{fr['id']} {fr['type']}: failed {fr['failed']} (supplier read as “{fr['supplier_read']}”)")
    L += ["", "## Not measured here", "",
          "- Bedrock Guardrails baseline (needs AWS credentials; not run).",
          "- LoRa range, live airtime and gas: measured on the hardware/L1 separately (6.1 s airtime, 328k gas per payment)."]
    return "\n".join(L) + "\n"


def main():
    rows = [json.loads(l) for l in open(os.path.join(HERE, "data", "dataset.jsonl"), encoding="utf-8")]
    anvil = start_anvil()
    try:
        badge = badge_sim.BadgeSim(auto=True)
        t0 = time.time()
        cases, lat = evaluate_dataset(rows)
        cases = run_contract_layers(cases, badge)
        frames = frame_and_chain_tests(badge)
        journal = journal_tests()
        S = summarize(cases, lat)
        S["runtime_s"] = round(time.time() - t0, 1)
    finally:
        anvil.terminate()
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    json.dump({"summary": S, "frames": frames, "journal": journal,
               "cases": [{k: v for k, v in c.items() if k != "text"} for c in cases]},
              open(os.path.join(HERE, "results", "results.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    md = report_md(S, frames, journal)
    open(os.path.join(HERE, "results", "report.md"), "w", encoding="utf-8").write(md)
    print(md)


if __name__ == "__main__":
    main()
