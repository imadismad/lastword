"""Generate proto/vectors.json with a fixed seed (I6).

Deterministic P-256 test keys are derived from a fixed seed so every run and every
machine produces the same vectors.json. These are TEST keys only - published, never
real. Run:  python -m lastword_proto.gen_vectors
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

from cryptography.hazmat.primitives.asymmetric import ec

from .intent import Intent, Role, Flag, digest
from .crypto import (
    pub_to_bytes, sign_digest, verify_digest, normalize_s, sig_to_bytes,
    build_request_frame, build_response_frame, open_frame,
)
from .serial import pack_message, unpack_message, Command

SEED = b"LASTWORD-proto-v1-fixed-seed"

# Deterministic test fixtures
CHAIN_ID = 31337
CONTRACT_ADDR = bytes.fromhex("00000000000000000000000000000000c0ffee11")
FRAME_KEY = hashlib.sha256(SEED + b"|framekey").digest()  # 32 bytes
BADGE_ID = 0x0000A001


def _deriv_key(label: str) -> ec.EllipticCurvePrivateKey:
    """Deterministic P-256 private key from the fixed seed (test only)."""
    h = int.from_bytes(hashlib.sha256(SEED + b"|" + label.encode()).digest(), "big")
    # map into [1, n-1]
    from .crypto import P256_N
    d = (h % (P256_N - 1)) + 1
    return ec.derive_private_key(d, ec.SECP256R1())


def _hex(b: bytes) -> str:
    return "0x" + b.hex()


def build() -> dict:
    stock = _deriv_key("stock")
    daf = _deriv_key("daf")
    duress = _deriv_key("duress")
    gateway = _deriv_key("gateway")

    keys = {
        "stock": {"priv": _hex(stock.private_numbers().private_value.to_bytes(32, "big")),
                  "pub": _hex(pub_to_bytes(stock.public_key()))},
        "daf": {"priv": _hex(daf.private_numbers().private_value.to_bytes(32, "big")),
                "pub": _hex(pub_to_bytes(daf.public_key()))},
        "duress": {"priv": _hex(duress.private_numbers().private_value.to_bytes(32, "big")),
                   "pub": _hex(pub_to_bytes(duress.public_key()))},
        "gateway": {"priv": _hex(gateway.private_numbers().private_value.to_bytes(32, "big")),
                    "pub": _hex(pub_to_bytes(gateway.public_key()))},
    }

    # --- sample intent (DAF approval) ---
    intent = Intent(
        reqId=1234,
        beneficiary=bytes.fromhex("1111111111111111111111111111111111111111"),
        token=0,
        amount=250_000_000,  # e.g. 250 USDC at 6 decimals
        nonce=7,
        deadline=1_760_000_000,
        quoteHash=hashlib.sha256(b"quote-doc-1").digest(),
        flags=int(Flag.NEW_BENEFICIARY | Flag.EXTERNAL_ORIGIN) | int(Role.DAF),
        policy=1,
    )
    intent_bytes = intent.encode()
    dg = digest(intent, CHAIN_ID, CONTRACT_ADDR)

    # DAF signature in both forms
    r, s_raw = sign_digest(daf, dg, low_s=False)
    s_low = normalize_s(s_raw)
    # Force a known high-s example: pick whichever of (s_raw, n-s_raw) is high
    from .crypto import P256_N
    s_high = s_raw if s_raw > P256_N // 2 else (P256_N - s_raw)

    assert verify_digest(daf.public_key(), dg, r, s_low)

    # --- stock intent (delivery attestation) ---
    stock_intent = Intent(
        reqId=1234,
        beneficiary=intent.beneficiary, token=0, amount=250_000_000,
        nonce=1, deadline=1_760_000_000,
        quoteHash=intent.quoteHash,
        flags=int(Role.STOCK), policy=1,
    )
    stock_dg = digest(stock_intent, CHAIN_ID, CONTRACT_ADDR)
    sr, ss = sign_digest(stock, stock_dg, low_s=True)

    # --- gateway signature over the DAF digest (for the request frame) ---
    gr, gs = sign_digest(gateway, dg, low_s=True)
    gateway_sig = sig_to_bytes(gr, gs)

    # --- sealed frames (I2) ---
    req_frame = build_request_frame(FRAME_KEY, BADGE_ID, counter=1,
                                    intent_bytes=intent_bytes, gateway_sig=gateway_sig)
    badge_sig = sig_to_bytes(r, s_low)
    resp_frame = build_response_frame(FRAME_KEY, BADGE_ID, counter=2,
                                      reqId=intent.reqId, decision=1, badge_sig=badge_sig)
    # round-trip sanity
    _h, _pt = open_frame(FRAME_KEY, req_frame)

    # --- I3 COBS messages ---
    hello = pack_message(Command.HELLO)
    hello_ok = pack_message(Command.HELLO_OK,
                            bytes.fromhex(keys["stock"]["pub"][2:])
                            + bytes.fromhex(keys["daf"]["pub"][2:])
                            + bytes.fromhex(keys["duress"]["pub"][2:]))
    provision = pack_message(Command.PROVISION,
                             FRAME_KEY + CHAIN_ID.to_bytes(8, "big") + CONTRACT_ADDR)
    request_msg = pack_message(Command.REQUEST, req_frame)
    response_msg = pack_message(Command.RESPONSE, resp_frame)

    # --- invalid cases ---
    bad_magic = bytearray(req_frame); bad_magic[0] ^= 0xFF
    bad_tag = bytearray(req_frame); bad_tag[-1] ^= 0xFF
    expired_intent = Intent(
        reqId=1234, beneficiary=intent.beneficiary, token=0, amount=250_000_000,
        nonce=7, deadline=1, quoteHash=intent.quoteHash,
        flags=int(Role.DAF), policy=1,
    )
    # swapped role: stock-signed digest presented as a DAF intent
    swapped_dg = digest(intent, CHAIN_ID, CONTRACT_ADDR)  # DAF intent digest
    swr, sws = sign_digest(stock, swapped_dg, low_s=True)  # but signed by STOCK key

    return {
        "meta": {
            "spec": "proto v1",
            "seed": SEED.decode(),
            "chainId": CHAIN_ID,
            "contractAddr": _hex(CONTRACT_ADDR),
            "frameKey": _hex(FRAME_KEY),
            "badgeId": BADGE_ID,
            "p256_n": "0x" + format(P256_N, "x"),
        },
        "keys": keys,
        "intent": {
            "fields": intent.to_json(),
            "bytes": _hex(intent_bytes),
            "digest": _hex(dg),
        },
        "stock_intent": {
            "fields": stock_intent.to_json(),
            "bytes": _hex(stock_intent.encode()),
            "digest": _hex(stock_dg),
            "sig_low_s": {"r": _hex(sr.to_bytes(32, "big")), "s": _hex(ss.to_bytes(32, "big"))},
        },
        "signatures": {
            "daf_low_s": {"r": _hex(r.to_bytes(32, "big")), "s": _hex(s_low.to_bytes(32, "big")),
                          "valid": True},
            "daf_high_s": {"r": _hex(r.to_bytes(32, "big")), "s": _hex(s_high.to_bytes(32, "big")),
                           "note": "same point, high-s; contract must reject"},
            "gateway_low_s": {"r": _hex(gr.to_bytes(32, "big")), "s": _hex(gs.to_bytes(32, "big"))},
        },
        "frames": {
            "request": _hex(req_frame),
            "response": _hex(resp_frame),
            "gateway_sig": _hex(gateway_sig),
            "badge_sig": _hex(badge_sig),
        },
        "serial": {
            "hello": _hex(hello),
            "hello_ok": _hex(hello_ok),
            "provision": _hex(provision),
            "request_msg": _hex(request_msg),
            "response_msg": _hex(response_msg),
        },
        "invalid": {
            "bad_magic_frame": _hex(bytes(bad_magic)),
            "bad_tag_frame": _hex(bytes(bad_tag)),
            "expired_intent_bytes": _hex(expired_intent.encode()),
            "expired_intent_digest": _hex(digest(expired_intent, CHAIN_ID, CONTRACT_ADDR)),
            "replayed_counter": 1,
            "swapped_role": {
                "intent_bytes": _hex(intent_bytes),
                "digest": _hex(swapped_dg),
                "signed_by": "stock",
                "r": _hex(swr.to_bytes(32, "big")), "s": _hex(sws.to_bytes(32, "big")),
                "note": "stock key signed a DAF-role intent; attestDelivery-vs-approve must reject",
            },
        },
    }


def main() -> None:
    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "vectors.json")
    if len(sys.argv) > 1:
        out_path = sys.argv[1]
    data = build()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
