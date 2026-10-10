"""verify — recompute the journal hash-chain and locate the first altered entry (T-07).

    python -m lastword_bridge.verify_cli bridge/journal.jsonl
    python -m lastword_bridge.verify_cli bridge/journal.jsonl --root
    python -m lastword_bridge.verify_cli bridge/journal.jsonl --anchors anchors.json

An auditor runs this WITHOUT access to the AWS account: it recomputes every hash and
the Merkle root and (optionally) compares the root to the on-chain / Fuji anchors.
Exit code 0 = intact, 2 = tampering detected.
"""
from __future__ import annotations

import argparse
import json
import sys

from .journal import Journal


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="path to the journal .jsonl")
    ap.add_argument("--root", action="store_true", help="print the Merkle root")
    ap.add_argument("--anchors", help="JSON list of anchored roots to compare against")
    args = ap.parse_args()

    ok, bad_seq, msg = Journal.verify(args.path)
    entries = Journal.read_all(args.path)
    print(f"entries: {len(entries)}")
    if ok:
        print(f"OK: {msg}")
    else:
        print(f"TAMPERING DETECTED at seq {bad_seq}: {msg}")

    root = Journal.merkle_root(args.path)
    if args.root or args.anchors:
        print(f"merkle_root: {root}")

    if args.anchors:
        anchors = json.load(open(args.anchors, encoding="utf-8"))
        if root in set(anchors):
            print("anchor match: current root is present in the anchor set")
        else:
            print("ANCHOR MISMATCH: current root is NOT in the anchor set "
                  "(entries changed since the last anchor, or anchors are stale)")
            ok = False

    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
