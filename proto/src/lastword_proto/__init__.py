"""LASTWORD frozen protocol library (proto v1).

Implements interfaces I1-I3 from proto/SPEC.md:
  - intent:  79-byte canonical payment intent + SHA-256 digest
  - crypto:  P-256 keys/sign/verify, low-s normalization, AES-256-GCM + HKDF frames
  - serial:  COBS + CRC-16 framed badge commands (I3)

No network, no hardware. Everything here is pure and deterministic.
"""

from .intent import (
    Intent,
    Role,
    Flag,
    INTENT_SIZE,
    DOMAIN_TAG,
    digest,
)
from .crypto import (
    P256_N,
    gen_keypair,
    pub_to_bytes,
    pub_from_bytes,
    sign_digest,
    verify_digest,
    normalize_s,
    is_low_s,
    hkdf_frame_key,
    seal_frame,
    open_frame,
    build_request_frame,
    build_response_frame,
    parse_request_body,
    parse_response_body,
    FrameHeader,
)
from .serial import (
    crc16_ccitt,
    cobs_encode,
    cobs_decode,
    pack_message,
    unpack_message,
    Command,
    RefuseReason,
)

__all__ = [
    "Intent", "Role", "Flag", "INTENT_SIZE", "DOMAIN_TAG", "digest",
    "P256_N", "gen_keypair", "pub_to_bytes", "pub_from_bytes",
    "sign_digest", "verify_digest", "normalize_s", "is_low_s",
    "hkdf_frame_key", "seal_frame", "open_frame",
    "build_request_frame", "build_response_frame",
    "parse_request_body", "parse_response_body", "FrameHeader",
    "crc16_ccitt", "cobs_encode", "cobs_decode",
    "pack_message", "unpack_message", "Command", "RefuseReason",
]

__version__ = "1.0.0"
