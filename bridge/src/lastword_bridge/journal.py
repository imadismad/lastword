"""Hash-chained decision journal (FR-12, cahier des charges s10).

Append-only JSONL. Each entry links to the previous by hash:
  hash = sha256(seq || ts || type || actor || reqId || payload_hash || prev_hash)
A Merkle root over all entries can be computed for on-chain anchoring (anchor(root)).
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from typing import Any

GENESIS_PREV = "0" * 64


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class Journal:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._seq = 0
        self._prev = GENESIS_PREV
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._load_tail()

    def _load_tail(self):
        if not os.path.exists(self.path):
            return
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                e = json.loads(line)
                self._seq = e["seq"]
                self._prev = e["hash"]
        self._seq += 0  # _seq is the last written seq

    def append(self, type_: str, actor: str, reqId: int, payload: dict) -> dict:
        with self._lock:
            seq = self._seq + 1
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            payload_hash = _sha(canonical(payload).encode())
            preimage = f"{seq}{ts}{type_}{actor}{reqId}{payload_hash}{self._prev}"
            h = _sha(preimage.encode())
            entry = {
                "seq": seq, "ts": ts, "type": type_, "actor": actor,
                "reqId": reqId, "payload": payload,
                "payload_hash": payload_hash, "prev_hash": self._prev, "hash": h,
            }
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            self._seq = seq
            self._prev = h
            return entry

    # ---- verification + Merkle root (used by the verify tool and anchoring) ----
    @staticmethod
    def read_all(path: str) -> list[dict]:
        out = []
        if not os.path.exists(path):
            return out
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    @staticmethod
    def verify(path: str) -> tuple[bool, int | None, str]:
        """Recompute the chain. Returns (ok, first_bad_seq, message)."""
        prev = GENESIS_PREV
        expected_seq = 1
        for e in Journal.read_all(path):
            if e["seq"] != expected_seq:
                return False, e["seq"], f"seq gap: expected {expected_seq} got {e['seq']}"
            payload_hash = _sha(canonical(e["payload"]).encode())
            if payload_hash != e["payload_hash"]:
                return False, e["seq"], "payload_hash mismatch (payload altered)"
            if e["prev_hash"] != prev:
                return False, e["seq"], "prev_hash mismatch (reordered/removed)"
            preimage = (f"{e['seq']}{e['ts']}{e['type']}{e['actor']}"
                        f"{e['reqId']}{e['payload_hash']}{e['prev_hash']}")
            if _sha(preimage.encode()) != e["hash"]:
                return False, e["seq"], "hash mismatch (entry altered)"
            prev = e["hash"]
            expected_seq += 1
        return True, None, "chain intact"

    @staticmethod
    def merkle_root(path: str) -> str:
        leaves = [bytes.fromhex(e["hash"]) for e in Journal.read_all(path)]
        if not leaves:
            return GENESIS_PREV
        level = leaves
        while len(level) > 1:
            nxt = []
            for i in range(0, len(level), 2):
                a = level[i]
                b = level[i + 1] if i + 1 < len(level) else level[i]
                nxt.append(hashlib.sha256(a + b).digest())
            level = nxt
        return level[0].hex()
