"""P-256 signatures (+ low-s normalization) and I2 AES-256-GCM radio frames.

See proto/SPEC.md sections I1 (signature form) and I2 (radio frame).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils as asym_utils
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# P-256 (secp256r1) curve order n
P256_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551

_HEADER = struct.Struct(">2s B B I I B")  # magic, version, type, badgeId, counter, bodyLen
HEADER_SIZE = _HEADER.size  # 13
MAGIC = b"LW"
TYPE_REQUEST = 0x01
TYPE_RESPONSE = 0x02


# --------------------------------------------------------------------------- keys
def gen_keypair() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def pub_to_bytes(pub: ec.EllipticCurvePublicKey) -> bytes:
    """Uncompressed X||Y, 64 bytes (no 0x04 prefix)."""
    raw = pub.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    assert raw[0] == 0x04 and len(raw) == 65
    return raw[1:]


def pub_from_bytes(data: bytes) -> ec.EllipticCurvePublicKey:
    if len(data) != 64:
        raise ValueError("pubkey must be 64 bytes (X||Y)")
    return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b"\x04" + data)


# ----------------------------------------------------------------- s normalization
def is_low_s(s: int) -> bool:
    return s <= P256_N // 2


def normalize_s(s: int) -> int:
    """Return low-s form required by OpenZeppelin P256.verify."""
    return P256_N - s if s > P256_N // 2 else s


def sign_digest(priv: ec.EllipticCurvePrivateKey, digest: bytes,
                low_s: bool = False) -> tuple[int, int]:
    """Sign a 32-byte digest. Returns (r, s). The curve does ECDSA over the digest
    treated as a pre-hashed value (Prehashed), i.e. the digest is NOT hashed again."""
    if len(digest) != 32:
        raise ValueError("digest must be 32 bytes")
    der = priv.sign(digest, ec.ECDSA(asym_utils.Prehashed(hashes.SHA256())))
    r, s = asym_utils.decode_dss_signature(der)
    if low_s:
        s = normalize_s(s)
    return r, s


def verify_digest(pub: ec.EllipticCurvePublicKey, digest: bytes,
                  r: int, s: int, require_low_s: bool = False) -> bool:
    if require_low_s and not is_low_s(s):
        return False
    der = asym_utils.encode_dss_signature(r, s)
    try:
        pub.verify(der, digest, ec.ECDSA(asym_utils.Prehashed(hashes.SHA256())))
        return True
    except Exception:
        return False


def sig_to_bytes(r: int, s: int) -> bytes:
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def sig_from_bytes(data: bytes) -> tuple[int, int]:
    if len(data) != 64:
        raise ValueError("signature must be 64 bytes (r||s)")
    return int.from_bytes(data[:32], "big"), int.from_bytes(data[32:], "big")


# -------------------------------------------------------------------- I2 AEAD frame
@dataclass
class FrameHeader:
    type: int
    badgeId: int
    counter: int
    bodyLen: int
    version: int = 1

    def pack(self) -> bytes:
        return _HEADER.pack(MAGIC, self.version, self.type, self.badgeId,
                            self.counter, self.bodyLen)

    @classmethod
    def unpack(cls, data: bytes) -> "FrameHeader":
        magic, version, typ, badgeId, counter, bodyLen = _HEADER.unpack(data[:HEADER_SIZE])
        if magic != MAGIC:
            raise ValueError("bad magic")
        return cls(type=typ, badgeId=badgeId, counter=counter,
                   bodyLen=bodyLen, version=version)


def hkdf_frame_key(frame_key: bytes, header: bytes) -> bytes:
    """Per-message key: HKDF-SHA256(frame_key, salt="", info=header) -> 32 bytes."""
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"",
                info=header).derive(frame_key)


def _gcm_nonce(type_: int, counter: int) -> bytes:
    # 0x00000000 || type(1) || counter(4 BE) || 0x000000  == 12 bytes
    return b"\x00\x00\x00\x00" + bytes([type_]) + counter.to_bytes(4, "big") + b"\x00\x00\x00"


def seal_frame(frame_key: bytes, type_: int, badgeId: int, counter: int,
               plaintext: bytes) -> bytes:
    header = FrameHeader(type=type_, badgeId=badgeId, counter=counter,
                         bodyLen=len(plaintext)).pack()
    key = hkdf_frame_key(frame_key, header)
    ct = AESGCM(key).encrypt(_gcm_nonce(type_, counter), plaintext, header)
    return header + ct  # ct already includes the 16-byte tag


def open_frame(frame_key: bytes, frame: bytes) -> tuple[FrameHeader, bytes]:
    header = FrameHeader.unpack(frame)
    hbytes = frame[:HEADER_SIZE]
    key = hkdf_frame_key(frame_key, hbytes)
    pt = AESGCM(key).decrypt(_gcm_nonce(header.type, header.counter),
                             frame[HEADER_SIZE:], hbytes)
    if len(pt) != header.bodyLen:
        raise ValueError("bodyLen mismatch")
    return header, pt


# --------------------------------------------------------- request/response bodies
def build_request_frame(frame_key: bytes, badgeId: int, counter: int,
                        intent_bytes: bytes, gateway_sig: bytes) -> bytes:
    if len(intent_bytes) != 79:
        raise ValueError("intent must be 79 bytes")
    if len(gateway_sig) != 64:
        raise ValueError("gateway_sig must be 64 bytes")
    return seal_frame(frame_key, TYPE_REQUEST, badgeId, counter,
                      intent_bytes + gateway_sig)


def parse_request_body(pt: bytes) -> tuple[bytes, bytes]:
    if len(pt) != 143:
        raise ValueError("request body must be 143 bytes")
    return pt[:79], pt[79:]  # intent, gateway_sig


def build_response_frame(frame_key: bytes, badgeId: int, counter: int,
                         reqId: int, decision: int, badge_sig: bytes) -> bytes:
    if len(badge_sig) != 64:
        raise ValueError("badge_sig must be 64 bytes")
    body = reqId.to_bytes(4, "big") + bytes([decision & 0xFF]) + badge_sig
    return seal_frame(frame_key, TYPE_RESPONSE, badgeId, counter, body)


def parse_response_body(pt: bytes) -> tuple[int, int, bytes]:
    if len(pt) != 69:
        raise ValueError("response body must be 69 bytes")
    reqId = int.from_bytes(pt[:4], "big")
    decision = pt[4]
    return reqId, decision, pt[5:]  # reqId, decision, badge_sig
