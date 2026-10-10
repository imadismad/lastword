"""Gateway signing key management.

The bridge (gateway) signs each request to the badge with a P-256 key. The badge
verifies this signature before displaying anything, so a hostile radio emitter cannot
make the badge show a forged request. The badge is given the gateway PUBLIC key.

The private key is persisted locally (gitignored). For the PoC/tests we can also
derive it deterministically from a seed so the badge-sim's default gateway pubkey
matches without an explicit handoff.
"""
from __future__ import annotations

import hashlib
import os

from cryptography.hazmat.primitives.asymmetric import ec
from lastword_proto import pub_to_bytes, sign_digest
from lastword_proto.crypto import P256_N, sig_to_bytes

_DEFAULT_SEED = b"lastword-badge-sim-v1"  # matches badge-sim's default seed


def _deriv(seed: bytes, label: str) -> ec.EllipticCurvePrivateKey:
    h = int.from_bytes(hashlib.sha256(seed + b"|" + label.encode()).digest(), "big")
    return ec.derive_private_key((h % (P256_N - 1)) + 1, ec.SECP256R1())


class GatewayKey:
    def __init__(self, priv: ec.EllipticCurvePrivateKey):
        self._priv = priv

    @classmethod
    def from_seed(cls, seed: bytes = _DEFAULT_SEED) -> "GatewayKey":
        """Deterministic key matching badge-sim's default gateway pubkey."""
        return cls(_deriv(seed, "gateway"))

    @classmethod
    def load_or_create(cls, path: str) -> "GatewayKey":
        if os.path.exists(path):
            with open(path, "rb") as f:
                d = int.from_bytes(f.read(32), "big")
            return cls(ec.derive_private_key(d, ec.SECP256R1()))
        key = ec.generate_private_key(ec.SECP256R1())
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "wb") as f:
            f.write(key.private_numbers().private_value.to_bytes(32, "big"))
        return cls(key)

    def public_bytes(self) -> bytes:
        return pub_to_bytes(self._priv.public_key())

    def public_hex(self) -> str:
        return self.public_bytes().hex()

    def sign(self, digest: bytes) -> bytes:
        """Low-s signature over the 32-byte digest, as r||s (64 bytes)."""
        r, s = sign_digest(self._priv, digest, low_s=True)
        return sig_to_bytes(r, s)
