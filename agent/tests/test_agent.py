"""Agent logic tests (reader + guard), no network. Validates the demo dataset verdicts."""
import json
import os
import sys

import jsonschema
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "proto", "src"))
sys.path.insert(0, os.path.join(ROOT, "agent", "src"))

from lastword_agent.reader import LocalReader
from lastword_agent.guard import Guard, DEFAULT_POLICY
from lastword_agent.agent import Agent
from lastword_agent.schema import READER_SCHEMA

DEMO = os.path.join(ROOT, "agent", "demo")
WL = json.load(open(os.path.join(DEMO, "whitelist.json"), encoding="utf-8"))


def _agent():
    return Agent("http://127.0.0.1:0", Guard(dict(DEFAULT_POLICY), WL), LocalReader())


def _read(name):
    return open(os.path.join(DEMO, name), encoding="utf-8").read()


def test_reader_output_matches_schema():
    r = LocalReader()
    out = r.read(_read("quote1_legit.txt"), known_suppliers=WL)
    jsonschema.validate(out, READER_SCHEMA)  # must not raise


def test_legit_quotes_ask_badge():
    a = _agent()
    for q in ("quote1_legit.txt", "quote2_legit.txt"):
        res = a.process(_read(q), deadline=9_999_999_999)
        assert res["verdict"] == "ASK_BADGE", f"{q}: {res['verdict']} {res['explanation']}"
        assert res["reasons"]["C1"] == "pass"


def test_injection_flagged_not_executed():
    a = _agent()
    res = a.process(_read("quote4_injection.txt"), deadline=9_999_999_999)
    # the hidden instruction is captured as a signal, never followed
    assert res["extracted"]["risk_signals"]["injection_suspected"] is True
    assert res["reasons"]["C12"] == "fail"
    # the attacker's non-hex address does not parse -> not a payable beneficiary
    assert res["verdict"] in ("REJECT", "ASK_BADGE")
    # score is elevated by the injection
    assert res["score"] >= 0.35


def test_address_changed_raises_signal():
    a = _agent()
    res = a.process(_read("quote3_address_changed.txt"), deadline=9_999_999_999)
    rs = res["extracted"]["risk_signals"]
    assert rs["address_changed"] is True
    # changed address breaks C1 (beneficiary != whitelisted) -> REJECT (hard)
    assert res["reasons"]["C1"] == "fail"
    assert res["verdict"] == "REJECT"


def test_unknown_supplier_rejected():
    a = _agent()
    res = a.process(_read("quote5_unknown_supplier.txt"), deadline=9_999_999_999)
    assert res["reasons"]["C1"] == "fail"      # not whitelisted
    assert res["verdict"] == "REJECT"
    assert res["extracted"]["risk_signals"]["urgency_pressure"] is True


def test_duplicate_quote_rejected():
    guard = Guard(dict(DEFAULT_POLICY), WL)
    a = Agent("http://127.0.0.1:0", guard, LocalReader())
    text = _read("quote1_legit.txt")
    first = a.process(text, deadline=9_999_999_999)
    assert first["verdict"] == "ASK_BADGE"
    # mark as seen, then re-process -> C6 duplicate fails
    guard.seen.add(first["quote_hash"])
    second = a.process(text, deadline=9_999_999_999)
    assert second["reasons"]["C6"] == "fail"
    assert second["verdict"] == "REJECT"


def test_agent_never_posts_non_ask_badge():
    a = _agent()
    res = a.process(_read("quote5_unknown_supplier.txt"), deadline=9_999_999_999)
    assert res["posted"] is False
