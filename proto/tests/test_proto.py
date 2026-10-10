"""Round-trip tests for the frozen proto lib + a vectors.json replay."""
import hashlib
import json
import os

import pytest

from lastword_proto import (
    Intent, Role, Flag, INTENT_SIZE, digest,
    gen_keypair, pub_to_bytes, pub_from_bytes, sign_digest, verify_digest,
    normalize_s, is_low_s, P256_N,
    seal_frame, open_frame, build_request_frame, build_response_frame,
    parse_request_body, parse_response_body,
    crc16_ccitt, cobs_encode, cobs_decode, pack_message, unpack_message, Command,
)
from lastword_proto.crypto import sig_to_bytes, sig_from_bytes
from lastword_proto import gen_vectors

VECTORS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "vectors.json")


# ------------------------------------------------------------------ intent (I1)
def test_intent_size_and_roundtrip():
    i = Intent(reqId=1, beneficiary=b"\x11" * 20, token=0, amount=1,
               nonce=0, deadline=100, quoteHash=b"\x22" * 32,
               flags=int(Role.DAF), policy=1)
    raw = i.encode()
    assert len(raw) == INTENT_SIZE == 79
    j = Intent.decode(raw)
    assert j.encode() == raw
    assert j.role == Role.DAF


def test_role_in_flags():
    i = Intent(reqId=1, beneficiary=b"\x00" * 20, token=0, amount=0, nonce=0,
               deadline=0, quoteHash=b"\x00" * 32)
    i.with_role(Role.STOCK)
    assert i.role == Role.STOCK
    i.flags |= int(Flag.NEW_BENEFICIARY)
    assert i.role == Role.STOCK  # role bits untouched
    assert i.flags & int(Flag.NEW_BENEFICIARY)


def test_intent_range_validation():
    with pytest.raises(ValueError):
        Intent(reqId=1 << 32, beneficiary=b"\x00" * 20, token=0, amount=0,
               nonce=0, deadline=0, quoteHash=b"\x00" * 32)
    with pytest.raises(ValueError):
        Intent(reqId=1, beneficiary=b"\x00" * 19, token=0, amount=0,
               nonce=0, deadline=0, quoteHash=b"\x00" * 32)


def test_digest_deterministic_and_domain_separated():
    i = Intent(reqId=1, beneficiary=b"\x11" * 20, token=0, amount=1,
               nonce=0, deadline=100, quoteHash=b"\x22" * 32, flags=int(Role.DAF))
    addr = bytes.fromhex("00000000000000000000000000000000c0ffee11")
    d1 = digest(i, 31337, addr)
    d2 = digest(i.encode(), 31337, addr)
    assert d1 == d2 and len(d1) == 32
    # changing chainId or address changes the digest
    assert digest(i, 43114, addr) != d1
    assert digest(i, 31337, b"\x00" * 20) != d1


# -------------------------------------------------------------- signatures (I1)
def test_sign_verify_and_low_s():
    k = gen_keypair()
    d = hashlib.sha256(b"hello").digest()
    r, s = sign_digest(k, d, low_s=True)
    assert is_low_s(s)
    assert verify_digest(k.public_key(), d, r, s)
    # high-s is still a valid signature mathematically, but fails require_low_s
    s_high = P256_N - s
    assert verify_digest(k.public_key(), d, r, s_high)         # valid point
    assert not verify_digest(k.public_key(), d, r, s_high, require_low_s=True)
    assert normalize_s(s_high) == s


def test_pub_bytes_roundtrip():
    k = gen_keypair()
    b = pub_to_bytes(k.public_key())
    assert len(b) == 64
    k2 = pub_from_bytes(b)
    assert pub_to_bytes(k2) == b


def test_wrong_key_fails():
    k1, k2 = gen_keypair(), gen_keypair()
    d = hashlib.sha256(b"x").digest()
    r, s = sign_digest(k1, d, low_s=True)
    assert not verify_digest(k2.public_key(), d, r, s)


# ---------------------------------------------------------------- AEAD frame (I2)
def test_frame_seal_open_roundtrip():
    key = b"\x33" * 32
    r, s = sign_digest(gen_keypair(), hashlib.sha256(b"d").digest())
    gsig = sig_to_bytes(r, s)
    intent = Intent(reqId=5, beneficiary=b"\x11" * 20, token=0, amount=9,
                    nonce=0, deadline=1, quoteHash=b"\x22" * 32,
                    flags=int(Role.DAF)).encode()
    frame = build_request_frame(key, badgeId=1, counter=1,
                                intent_bytes=intent, gateway_sig=gsig)
    hdr, pt = open_frame(key, frame)
    assert hdr.type == 0x01 and hdr.counter == 1
    got_intent, got_sig = parse_request_body(pt)
    assert got_intent == intent and got_sig == gsig


def test_frame_tamper_detected():
    key = b"\x44" * 32
    frame = bytearray(seal_frame(key, 0x02, 1, 1, b"\x01" * 10))
    frame[-1] ^= 0x01  # flip a tag bit
    with pytest.raises(Exception):
        open_frame(key, bytes(frame))


def test_response_frame_roundtrip():
    key = b"\x55" * 32
    sig = sig_to_bytes(*sign_digest(gen_keypair(), hashlib.sha256(b"z").digest()))
    frame = build_response_frame(key, badgeId=1, counter=2, reqId=77,
                                 decision=1, badge_sig=sig)
    _hdr, pt = open_frame(key, frame)
    reqId, decision, badge_sig = parse_response_body(pt)
    assert reqId == 77 and decision == 1 and badge_sig == sig


# ------------------------------------------------------------- serial COBS (I3)
def test_crc16_known_vector():
    # CRC-16/CCITT-FALSE("123456789") == 0x29B1
    assert crc16_ccitt(b"123456789") == 0x29B1


@pytest.mark.parametrize("payload", [
    b"", b"\x00", b"\x00\x00", b"\x01\x02\x03", b"\x00" * 300,
    bytes(range(256)), b"hello\x00world",
])
def test_cobs_roundtrip(payload):
    enc = cobs_encode(payload)
    assert 0 not in enc  # COBS output has no zero bytes
    assert cobs_decode(enc) == payload


def test_message_roundtrip_and_crc():
    msg = pack_message(Command.REQUEST, b"\xDE\xAD\xBE\xEF")
    assert msg.endswith(b"\x00")
    cmd, data = unpack_message(msg)
    assert cmd == Command.REQUEST and data == b"\xDE\xAD\xBE\xEF"


def test_message_crc_mismatch_raises():
    msg = bytearray(pack_message(Command.HELLO, b"abc"))
    msg[2] ^= 0xFF  # corrupt a data byte inside the COBS frame
    with pytest.raises(ValueError):
        unpack_message(bytes(msg))


# --------------------------------------------------------- vectors.json replay (I6)
@pytest.fixture(scope="module")
def vectors():
    if not os.path.exists(VECTORS_PATH):
        gen_vectors.main()
    with open(VECTORS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _b(h):
    return bytes.fromhex(h[2:] if h.startswith("0x") else h)


def test_vectors_intent_digest(vectors):
    intent_bytes = _b(vectors["intent"]["bytes"])
    assert len(intent_bytes) == 79
    i = Intent.decode(intent_bytes)
    assert i.encode() == intent_bytes
    chain_id = vectors["meta"]["chainId"]
    addr = _b(vectors["meta"]["contractAddr"])
    assert digest(i, chain_id, addr) == _b(vectors["intent"]["digest"])


def test_vectors_daf_signature(vectors):
    pub = pub_from_bytes(_b(vectors["keys"]["daf"]["pub"]))
    d = _b(vectors["intent"]["digest"])
    low = vectors["signatures"]["daf_low_s"]
    r, s = int(low["r"], 16), int(low["s"], 16)
    assert is_low_s(s)
    assert verify_digest(pub, d, r, s, require_low_s=True)
    # high-s: same point, must be rejected by the low-s rule
    high = vectors["signatures"]["daf_high_s"]
    rh, sh = int(high["r"], 16), int(high["s"], 16)
    assert verify_digest(pub, d, rh, sh)                       # mathematically valid
    assert not verify_digest(pub, d, rh, sh, require_low_s=True)


def test_vectors_frames_open(vectors):
    key = _b(vectors["meta"]["frameKey"])
    hdr, pt = open_frame(key, _b(vectors["frames"]["request"]))
    intent_bytes, gsig = parse_request_body(pt)
    assert intent_bytes == _b(vectors["intent"]["bytes"])
    assert gsig == _b(vectors["frames"]["gateway_sig"])
    # gateway sig verifies against gateway pubkey over the digest
    gpub = pub_from_bytes(_b(vectors["keys"]["gateway"]["pub"]))
    gr, gs = sig_from_bytes(gsig)
    assert verify_digest(gpub, _b(vectors["intent"]["digest"]), gr, gs)


def test_vectors_response_frame(vectors):
    key = _b(vectors["meta"]["frameKey"])
    _hdr, pt = open_frame(key, _b(vectors["frames"]["response"]))
    reqId, decision, badge_sig = parse_response_body(pt)
    assert reqId == vectors["intent"]["fields"]["reqId"]
    assert decision == 1
    pub = pub_from_bytes(_b(vectors["keys"]["daf"]["pub"]))
    r, s = sig_from_bytes(badge_sig)
    assert verify_digest(pub, _b(vectors["intent"]["digest"]), r, s, require_low_s=True)


def test_vectors_serial_messages(vectors):
    cmd, data = unpack_message(_b(vectors["serial"]["request_msg"]))
    assert cmd == Command.REQUEST
    assert data == _b(vectors["frames"]["request"])
    cmd2, data2 = unpack_message(_b(vectors["serial"]["hello_ok"]))
    assert cmd2 == Command.HELLO_OK and len(data2) == 192  # 3 x 64


def test_vectors_invalid_cases(vectors):
    key = _b(vectors["meta"]["frameKey"])
    with pytest.raises(Exception):
        open_frame(key, _b(vectors["invalid"]["bad_magic_frame"]))
    with pytest.raises(Exception):
        open_frame(key, _b(vectors["invalid"]["bad_tag_frame"]))
    # swapped role: stock key signed a DAF-role digest -> verifies under stock pub
    sw = vectors["invalid"]["swapped_role"]
    stock_pub = pub_from_bytes(_b(vectors["keys"]["stock"]["pub"]))
    daf_pub = pub_from_bytes(_b(vectors["keys"]["daf"]["pub"]))
    r, s = int(sw["r"], 16), int(sw["s"], 16)
    d = _b(sw["digest"])
    assert verify_digest(stock_pub, d, r, s)        # it IS a valid stock sig
    assert not verify_digest(daf_pub, d, r, s)      # but NOT a valid DAF sig
