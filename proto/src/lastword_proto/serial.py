"""I3 - badge serial link: COBS framing + CRC-16/CCITT-FALSE messages.

See proto/SPEC.md section I3. Message layout before COBS:
    command(1) | length(2 BE) | data(length) | crc16(2 BE)
then COBS-encoded and terminated with 0x00.
"""
from __future__ import annotations

from enum import IntEnum


class Command(IntEnum):
    HELLO = 0x01
    HELLO_OK = 0x81
    PROVISION = 0x02
    PROV_OK = 0x82
    REQUEST = 0x03
    RESPONSE = 0x83
    REFUSED = 0x84


class RefuseReason(IntEnum):
    BAD_GATEWAY_SIG = 0x01
    BAD_AEAD = 0x02
    USER_REFUSED = 0x03
    EXPIRED = 0x04
    NOT_PROVISIONED = 0x05
    OTHER = 0xFF


# ------------------------------------------------------------------ CRC-16/CCITT
def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection, no xorout."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


# -------------------------------------------------------------------------- COBS
def cobs_encode(data: bytes) -> bytes:
    """Consistent Overhead Byte Stuffing (no trailing delimiter added here)."""
    out = bytearray()
    idx = 0
    while True:
        # find next zero or end
        block = bytearray([0])  # placeholder for code byte
        count = 1
        while idx < len(data) and data[idx] != 0 and count < 0xFF:
            block.append(data[idx])
            idx += 1
            count += 1
        block[0] = count
        out += block
        if idx < len(data) and data[idx] == 0:
            idx += 1
            if idx == len(data):
                # trailing zero: needs a final 0x01 code block
                out += bytes([0x01])
                break
        elif idx >= len(data):
            break
    return bytes(out)


def cobs_decode(data: bytes) -> bytes:
    out = bytearray()
    idx = 0
    while idx < len(data):
        code = data[idx]
        idx += 1
        if code == 0:
            raise ValueError("unexpected zero byte in COBS data")
        if idx + (code - 1) > len(data):
            raise ValueError("COBS code points past end of buffer")
        out += data[idx:idx + code - 1]
        idx += code - 1
        if code < 0xFF and idx < len(data):
            out.append(0)
    return bytes(out)


# ---------------------------------------------------------------------- messages
def pack_message(command: int, data: bytes = b"") -> bytes:
    """Build a full COBS-framed message terminated by 0x00."""
    if len(data) > 0xFFFF:
        raise ValueError("data too long")
    body = bytes([command]) + len(data).to_bytes(2, "big") + data
    crc = crc16_ccitt(body)
    raw = body + crc.to_bytes(2, "big")
    return cobs_encode(raw) + b"\x00"


def unpack_message(framed: bytes) -> tuple[int, bytes]:
    """Decode one COBS frame (with or without trailing 0x00). Returns (command, data).
    Raises ValueError on CRC mismatch or malformed length."""
    if framed.endswith(b"\x00"):
        framed = framed[:-1]
    raw = cobs_decode(framed)
    if len(raw) < 5:
        raise ValueError("message too short")
    command = raw[0]
    length = int.from_bytes(raw[1:3], "big")
    data = raw[3:3 + length]
    if len(data) != length:
        raise ValueError("truncated data")
    crc_recv = int.from_bytes(raw[3 + length:3 + length + 2], "big")
    crc_calc = crc16_ccitt(raw[:3 + length])
    if crc_recv != crc_calc:
        raise ValueError(f"CRC mismatch: got {crc_recv:#06x} want {crc_calc:#06x}")
    return command, data
