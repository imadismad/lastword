"""Agent CLI: process a quote file (txt/eml/pdf) and optionally post to the bridge.

    python -m lastword_agent.cli quote.txt --bridge http://127.0.0.1:8099 \
        --deadline-mins 10

Reads whitelist/policy from a JSON file (--whitelist). Bedrock is used only if
--bedrock-model is given AND reachable; otherwise the local deterministic reader runs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from .agent import Agent
from .guard import Guard, DEFAULT_POLICY
from .reader import make_reader


def load_quote(path: str) -> str:
    data = open(path, "rb").read()
    low = path.lower()
    if low.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            import io
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
        hdr = f"From: {msg.get('From','')}\nSubject: {msg.get('Subject','')}\n"
        return hdr + "\n".join(parts)
    return data.decode("utf-8", "ignore")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("quote", help="path to the quote file (txt/eml/pdf)")
    ap.add_argument("--bridge", default=os.environ.get("BRIDGE_URL", "http://127.0.0.1:8099"))
    ap.add_argument("--whitelist", help="JSON file: supplier -> {beneficiary,cap,active}")
    ap.add_argument("--deadline-mins", type=int, default=10)
    ap.add_argument("--token", type=int, default=0)
    ap.add_argument("--no-post", action="store_true", help="evaluate only, do not POST")
    ap.add_argument("--bedrock-model", default=os.environ.get("BEDROCK_MODEL_ID", ""))
    ap.add_argument("--region", default=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    ap.add_argument("--guardrail", default=os.environ.get("BEDROCK_GUARDRAIL_ID"))
    args = ap.parse_args()

    whitelist = {}
    if args.whitelist and os.path.exists(args.whitelist):
        whitelist = json.load(open(args.whitelist))

    reader = make_reader(prefer_bedrock=bool(args.bedrock_model),
                         model_id=args.bedrock_model, region=args.region,
                         guardrail_id=args.guardrail)
    guard = Guard(policy=dict(DEFAULT_POLICY), whitelist=whitelist)
    agent = Agent(args.bridge, guard, reader=reader)

    text = load_quote(args.quote)
    deadline = int(time.time()) + args.deadline_mins * 60

    if args.no_post:
        # evaluate without touching the bridge
        agent.bridge_url = "http://127.0.0.1:0"  # ensure no accidental post
    result = agent.process(text, deadline=deadline, token=args.token)
    # never print keys or secrets - result has none
    print(json.dumps({k: v for k, v in result.items() if k != "extracted"}, indent=2))
    print("--- extracted (reader output, data only) ---")
    print(json.dumps(result.get("extracted", {}), indent=2))
    sys.exit(0 if result["verdict"] != "REJECT" else 3)


if __name__ == "__main__":
    main()
