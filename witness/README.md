# witness — external anchor of the journal root (cahier des charges §10)

The journal proves a decision was not rewritten *after the fact* — but only if its root
is anchored outside the control of whoever writes it. The witness publishes the journal
Merkle root to two independent external places (both optional):

1. **Fuji** (Avalanche public testnet) — a benign data transaction carrying the root
   (`0x4c57 || root`). A third party verifies the root existed at a point in time
   without any access to our AWS account. (`--fuji`, needs `WITNESS_PRIVATE_KEY` and a
   little test AVAX.)
2. **S3 Object Lock (WORM)** — writes the root + timestamp to a bucket with a compliance
   retention lock, so it cannot be overwritten or deleted. (`--s3-bucket`.)

It **always** records the anchor locally (`witness/anchors.json`), and it never pretends
an anchor happened: if Fuji or S3 is unreachable (e.g. the Dell's filtered network) it
reports exactly what succeeded and what did not.

Meant to run on **EC2** (the hybrid PoC's cloud witness). Degrades to local-only
elsewhere.

```
python witness/witness.py --journal bridge/journal.jsonl --fuji --s3-bucket my-lock-bucket
```

## Auditor flow (no AWS access needed)

```
python -m lastword_bridge.verify_cli bridge/journal.jsonl --anchors witness/anchors.json
```
`verify` recomputes the chain and the root and checks the root is present in the anchor
set. Exit 0 = intact and anchored; exit 2 = tampering or stale anchor. Tamper detection
(modify / delete / reorder) is covered by `bridge/tests/test_journal.py` (T-07, 5 tests).
