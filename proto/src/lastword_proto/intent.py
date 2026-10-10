"""I1 - the 79-byte canonical payment intent and its SHA-256 digest.

See proto/SPEC.md, section I1. All multi-byte integers are big-endian.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from enum import IntEnum, IntFlag

INTENT_SIZE = 79
DOMAIN_TAG = b"LASTWORD-v1"  # 11 ASCII bytes


class Role(IntEnum):
    """Role encoded in flags bits 0-1. Part of the signed digest."""
    UNSET = 0b00
    STOCK = 0b01   # delivery attestation
    DAF = 0b10     # payment approval
    RESERVED = 0b11


class Flag(IntFlag):
    """Verdict-reason indicators (flags bits 2+). Role lives in bits 0-1 separately."""
    NEW_BENEFICIARY = 1 << 2
    EXTERNAL_ORIGIN = 1 << 3
    ATYPICAL_AMOUNT = 1 << 4
    INJECTION_SUSPECTED = 1 << 5
    ADDRESS_CHANGED = 1 << 6
    DURESS = 1 << 7  # internal-only; never emitted on wire or on-chain


_STRUCT = struct.Struct(">BB I 20s B Q I I 32s H H")
# version, algorithm, reqId, beneficiary, token, amount, nonce, deadline,
# quoteHash, flags, policy
assert _STRUCT.size == INTENT_SIZE, _STRUCT.size


@dataclass
class Intent:
    reqId: int
    beneficiary: bytes          # 20 bytes
    token: int
    amount: int
    nonce: int
    deadline: int
    quoteHash: bytes            # 32 bytes
    flags: int = 0
    policy: int = 1
    version: int = 1
    algorithm: int = 1          # 1 = ECDSA P-256

    def __post_init__(self) -> None:
        if len(self.beneficiary) != 20:
            raise ValueError("beneficiary must be 20 bytes")
        if len(self.quoteHash) != 32:
            raise ValueError("quoteHash must be 32 bytes")
        for name, val, bits in [
            ("reqId", self.reqId, 32), ("token", self.token, 8),
            ("amount", self.amount, 64), ("nonce", self.nonce, 32),
            ("deadline", self.deadline, 32), ("flags", self.flags, 16),
            ("policy", self.policy, 16), ("version", self.version, 8),
            ("algorithm", self.algorithm, 8),
        ]:
            if not (0 <= val < (1 << bits)):
                raise ValueError(f"{name} out of range for u{bits}: {val}")

    # ----- role helpers (flags bits 0-1) -----
    @property
    def role(self) -> Role:
        return Role(self.flags & 0b11)

    def with_role(self, role: Role) -> "Intent":
        self.flags = (self.flags & ~0b11) | int(role)
        return self

    # ----- codec -----
    def encode(self) -> bytes:
        return _STRUCT.pack(
            self.version, self.algorithm, self.reqId, self.beneficiary,
            self.token, self.amount, self.nonce, self.deadline,
            self.quoteHash, self.flags, self.policy,
        )

    @classmethod
    def decode(cls, data: bytes) -> "Intent":
        if len(data) != INTENT_SIZE:
            raise ValueError(f"intent must be {INTENT_SIZE} bytes, got {len(data)}")
        (version, algorithm, reqId, beneficiary, token, amount, nonce,
         deadline, quoteHash, flags, policy) = _STRUCT.unpack(data)
        return cls(
            reqId=reqId, beneficiary=beneficiary, token=token, amount=amount,
            nonce=nonce, deadline=deadline, quoteHash=quoteHash, flags=flags,
            policy=policy, version=version, algorithm=algorithm,
        )

    def to_json(self) -> dict:
        return {
            "version": self.version, "algorithm": self.algorithm,
            "reqId": self.reqId, "beneficiary": "0x" + self.beneficiary.hex(),
            "token": self.token, "amount": self.amount, "nonce": self.nonce,
            "deadline": self.deadline, "quoteHash": "0x" + self.quoteHash.hex(),
            "flags": self.flags, "policy": self.policy, "role": int(self.role),
        }


def digest(intent: Intent | bytes, chain_id: int, contract_addr: bytes) -> bytes:
    """SHA-256( DOMAIN_TAG || chainId(8 BE) || contractAddr(20) || intent(79) )."""
    raw = intent.encode() if isinstance(intent, Intent) else intent
    if len(raw) != INTENT_SIZE:
        raise ValueError("intent must be 79 bytes")
    if len(contract_addr) != 20:
        raise ValueError("contract_addr must be 20 bytes")
    preimage = DOMAIN_TAG + chain_id.to_bytes(8, "big") + contract_addr + raw
    return hashlib.sha256(preimage).digest()
