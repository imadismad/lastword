#pragma once

// wire.h — pure framing/codec helpers for I3 (COBS + CRC-16) and I1 intent, with
// NO hardware and NO crypto-provider dependency. These are byte-for-byte ports of
// proto/src/lastword_proto/serial.py and intent.py, so they can be compiled and
// unit-tested on a host against proto/vectors.json (see test/).
//
// AEAD (AES-256-GCM), HKDF and SHA-256 live behind ICrypto (crypto.h) because the
// provider differs between device (mbedTLS/PSA in ESP-IDF) and host test (OpenSSL
// or a vendored mbedTLS). Keeping the framing here, provider-agnostic, keeps the
// bulk of the logic trivially testable.

#include <cstddef>
#include <cstdint>

namespace cdc::mod_lastword::wire {

// ----- CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection, no xorout ---
uint16_t crc16_ccitt(const uint8_t* data, size_t len);

// ----- COBS (mirrors serial.py cobs_encode/decode, incl. the trailing-zero case) -
// Encodes `in` into `out` (no 0x00 delimiter appended). Returns bytes written, or
// 0 if it would overflow outCap.
size_t cobs_encode(const uint8_t* in, size_t len, uint8_t* out, size_t outCap);
// Decodes COBS `in` (delimiter must already be stripped). Returns decoded length,
// or SIZE_MAX on malformed input / overflow.
size_t cobs_decode(const uint8_t* in, size_t len, uint8_t* out, size_t outCap);

// ----- I3 message framing ------------------------------------------------------
// Build a full COBS frame terminated by 0x00 for (command, data). Layout before
// COBS: command(1) | len(2 BE) | data | crc16(2 BE). Returns frame length in `out`
// or 0 on overflow / data too long.
size_t pack_message(uint8_t command, const uint8_t* data, size_t len,
                    uint8_t* out, size_t outCap);
// Parse one COBS frame (trailing 0x00 optional). On success writes the command to
// *cmd, copies the payload into `data` (bounded by dataCap) and sets *dataLen.
// Returns true on success, false on CRC/length/overflow error.
bool unpack_message(const uint8_t* framed, size_t len,
                    uint8_t* cmd, uint8_t* data, size_t dataCap, size_t* dataLen);

// ----- I2 clear header (13 bytes, big-endian), proto/SPEC.md I2 ----------------
struct FrameHeader {
    uint8_t  version;   // = 1
    uint8_t  type;      // 0x01 request, 0x02 response
    uint32_t badgeId;
    uint32_t counter;
    uint8_t  bodyLen;
    void pack(uint8_t out13[13]) const;
    static bool unpack(const uint8_t in[13], FrameHeader& out); // checks magic "LW"
};
constexpr size_t HEADER_SIZE = 13;
constexpr uint8_t TYPE_REQUEST = 0x01;
constexpr uint8_t TYPE_RESPONSE = 0x02;

// 12-byte deterministic GCM nonce: 0x00000000 || type(1) || counter(4 BE) || 0x000000
void gcm_nonce(uint8_t type_, uint32_t counter, uint8_t out12[12]);

} // namespace cdc::mod_lastword::wire
