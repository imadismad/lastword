"""witness — anchor the journal Merkle root externally (cahier des charges s10).

Two external witnesses, both optional and independent:
  1. Fuji: send the root as a data transaction (benign) so a third party can see,
     without our AWS account, that the root existed at a point in time.
  2. S3 with Object Lock (WORM): write the root + metadata to a bucket with a
     retention lock so it cannot be overwritten or deleted.

Designed to run on EC2 (us-east-1/us-west-2). Degrades gracefully: if Fuji or S3 is
unreachable (e.g. from the Dell's filtered network), it records the anchor locally and
reports what it could and could not do - it never pretends an anchor happened.

Usage:
  python witness/witness.py --journal bridge/journal.jsonl \
      --s3-bucket my-lock-bucket [--fuji] [--region us-east-1]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "proto", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "bridge", "src"))

from lastword_bridge.journal import Journal

FUJI_RPC = "https://api.avax-test.network/ext/bc/C/rpc"
FUJI_CHAIN_ID = 43113


def anchor_fuji(root: str, private_key: str) -> dict:
    """Send a 0-value tx to self with the root (0x..) in the data field on Fuji C-Chain."""
    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider(FUJI_RPC))
    if not w3.is_connected():
        return {"ok": False, "error": "Fuji RPC unreachable"}
    acct = w3.eth.account.from_key(private_key)
    tx = {
        "to": acct.address,
        "value": 0,
        "nonce": w3.eth.get_transaction_count(acct.address),
        "gas": 50_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": FUJI_CHAIN_ID,
        "data": "0x4c57" + root,  # "LW" || root hex
    }
    signed = acct.sign_transaction(tx)
    txh = w3.eth.send_raw_transaction(signed.raw_transaction)
    rc = w3.eth.wait_for_transaction_receipt(txh, timeout=120)
    return {"ok": rc.status == 1, "tx": txh.hex(),
            "explorer": f"https://testnet.snowtrace.io/tx/{txh.hex()}"}


def anchor_s3(root: str, bucket: str, region: str, key: str | None = None) -> dict:
    """Put the root + metadata into an Object-Lock bucket (WORM)."""
    import boto3
    s3 = boto3.client("s3", region_name=region)
    key = key or f"anchors/{int(time.time())}-{root[:12]}.json"
    body = json.dumps({"root": root, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       "domain": "LASTWORD-journal-root"}).encode()
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=body,
                      ObjectLockMode="COMPLIANCE",
                      ObjectLockRetainUntilDate=time.strftime(
                          "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 7 * 86400)))
        return {"ok": True, "bucket": bucket, "key": key, "lock": "COMPLIANCE+7d"}
    except Exception as e:
        # bucket may not have object-lock enabled; try a plain put so the demo still works
        try:
            s3.put_object(Bucket=bucket, Key=key, Body=body)
            return {"ok": True, "bucket": bucket, "key": key, "lock": "none (object-lock not enabled)",
                    "warning": str(e)}
        except Exception as e2:
            return {"ok": False, "error": str(e2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--journal", required=True)
    ap.add_argument("--s3-bucket")
    ap.add_argument("--fuji", action="store_true")
    ap.add_argument("--region", default=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    ap.add_argument("--out", default="witness/anchors.json",
                    help="local record of all anchors (always written)")
    args = ap.parse_args()

    ok, bad, msg = Journal.verify(args.journal)
    root = Journal.merkle_root(args.journal)
    print(f"journal verify: {'OK' if ok else f'TAMPERED at {bad}'} ({msg})")
    print(f"merkle_root: {root}")

    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "root": root, "journal_ok": ok}

    if args.fuji:
        pk = os.environ.get("WITNESS_PRIVATE_KEY")
        if not pk:
            record["fuji"] = {"ok": False, "error": "WITNESS_PRIVATE_KEY not set"}
        else:
            record["fuji"] = anchor_fuji(root, pk)
        print(f"fuji: {record['fuji']}")

    if args.s3_bucket:
        record["s3"] = anchor_s3(root, args.s3_bucket, args.region)
        print(f"s3: {record['s3']}")

    # always append to the local anchor list (the auditor compares roots to these)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    existing = []
    if os.path.exists(args.out):
        existing = json.load(open(args.out, encoding="utf-8"))
    existing.append(record)
    json.dump(existing, open(args.out, "w", encoding="utf-8"), indent=2)
    print(f"recorded anchor locally in {args.out}")


if __name__ == "__main__":
    main()
