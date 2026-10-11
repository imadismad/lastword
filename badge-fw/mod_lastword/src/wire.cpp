#include "mod_lastword/wire.h"

#include <cstring>

namespace cdc::mod_lastword::wire {

static constexpr uint8_t MAGIC0 = 'L'; // 0x4C
static constexpr uint8_t MAGIC1 = 'W'; // 0x57

uint16_t crc16_ccitt(const uint8_t* data, size_t len) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; ++i) {
        crc ^= static_cast<uint16_t>(data[i]) << 8;
        for (int b = 0; b < 8; ++b) {
            if (crc & 0x8000) {
                crc = static_cast<uint16_t>((crc << 1) ^ 0x1021);
            } else {
                crc = static_cast<uint16_t>(crc << 1);
            }
        }
    }
    return crc;
}

// Mirrors serial.py cobs_encode exactly, including the trailing-zero handling that
// appends a final 0x01 code block when the input ends on a zero byte.
size_t cobs_encode(const uint8_t* in, size_t len, uint8_t* out, size_t outCap) {
    size_t idx = 0, o = 0;
    for (;;) {
        // reserve a code byte, then copy a run of non-zero bytes (max 0xFF-1).
        if (o >= outCap) return 0;
        size_t codePos = o++;
        uint8_t count = 1;
        while (idx < len && in[idx] != 0 && count < 0xFF) {
            if (o >= outCap) return 0;
            out[o++] = in[idx++];
            ++count;
        }
        out[codePos] = count;
        if (idx < len && in[idx] == 0) {
            ++idx;
            if (idx == len) {
                // trailing zero: emit a final 0x01 code block
                if (o >= outCap) return 0;
                out[o++] = 0x01;
                break;
            }
        } else if (idx >= len) {
            break;
        }
    }
    return o;
}

size_t cobs_decode(const uint8_t* in, size_t len, uint8_t* out, size_t outCap) {
    size_t idx = 0, o = 0;
    while (idx < len) {
        uint8_t code = in[idx++];
        if (code == 0) return SIZE_MAX; // unexpected zero
        if (idx + (code - 1u) > len) return SIZE_MAX; // points past end
        for (uint8_t k = 1; k < code; ++k) {
            if (o >= outCap) return SIZE_MAX;
            out[o++] = in[idx++];
        }
        if (code < 0xFF && idx < len) {
            if (o >= outCap) return SIZE_MAX;
            out[o++] = 0;
        }
    }
    return o;
}

size_t pack_message(uint8_t command, const uint8_t* data, size_t len,
                    uint8_t* out, size_t outCap) {
    if (len > 0xFFFF) return 0;
    // raw = command(1) | len(2 BE) | data | crc16(2 BE)
    uint8_t raw[300];
    const size_t rawLen = 1 + 2 + len + 2;
    if (rawLen > sizeof(raw)) return 0;
    raw[0] = command;
    raw[1] = static_cast<uint8_t>((len >> 8) & 0xFF);
    raw[2] = static_cast<uint8_t>(len & 0xFF);
    if (len) std::memcpy(raw + 3, data, len);
    uint16_t crc = crc16_ccitt(raw, 3 + len);
    raw[3 + len] = static_cast<uint8_t>((crc >> 8) & 0xFF);
    raw[3 + len + 1] = static_cast<uint8_t>(crc & 0xFF);

    size_t n = cobs_encode(raw, rawLen, out, outCap);
    if (n == 0 || n + 1 > outCap) return 0;
    out[n] = 0x00; // delimiter
    return n + 1;
}

bool unpack_message(const uint8_t* framed, size_t len,
                    uint8_t* cmd, uint8_t* data, size_t dataCap, size_t* dataLen) {
    if (len && framed[len - 1] == 0x00) --len; // strip delimiter if present
    uint8_t raw[300];
    size_t rawLen = cobs_decode(framed, len, raw, sizeof(raw));
    if (rawLen == SIZE_MAX || rawLen < 5) return false;
    uint8_t command = raw[0];
    size_t length = (static_cast<size_t>(raw[1]) << 8) | raw[2];
    if (3 + length + 2 > rawLen) return false;
    uint16_t crcRecv = static_cast<uint16_t>((raw[3 + length] << 8) | raw[3 + length + 1]);
    uint16_t crcCalc = crc16_ccitt(raw, 3 + length);
    if (crcRecv != crcCalc) return false;
    if (length > dataCap) return false;
    if (length) std::memcpy(data, raw + 3, length);
    *cmd = command;
    *dataLen = length;
    return true;
}

void FrameHeader::pack(uint8_t out13[13]) const {
    out13[0] = MAGIC0;
    out13[1] = MAGIC1;
    out13[2] = version;
    out13[3] = type;
    out13[4] = static_cast<uint8_t>((badgeId >> 24) & 0xFF);
    out13[5] = static_cast<uint8_t>((badgeId >> 16) & 0xFF);
    out13[6] = static_cast<uint8_t>((badgeId >> 8) & 0xFF);
    out13[7] = static_cast<uint8_t>(badgeId & 0xFF);
    out13[8] = static_cast<uint8_t>((counter >> 24) & 0xFF);
    out13[9] = static_cast<uint8_t>((counter >> 16) & 0xFF);
    out13[10] = static_cast<uint8_t>((counter >> 8) & 0xFF);
    out13[11] = static_cast<uint8_t>(counter & 0xFF);
    out13[12] = bodyLen;
}

bool FrameHeader::unpack(const uint8_t in[13], FrameHeader& out) {
    if (in[0] != MAGIC0 || in[1] != MAGIC1) return false;
    out.version = in[2];
    out.type = in[3];
    out.badgeId = (static_cast<uint32_t>(in[4]) << 24) | (static_cast<uint32_t>(in[5]) << 16) |
                  (static_cast<uint32_t>(in[6]) << 8) | in[7];
    out.counter = (static_cast<uint32_t>(in[8]) << 24) | (static_cast<uint32_t>(in[9]) << 16) |
                  (static_cast<uint32_t>(in[10]) << 8) | in[11];
    out.bodyLen = in[12];
    return true;
}

void gcm_nonce(uint8_t type_, uint32_t counter, uint8_t out12[12]) {
    out12[0] = out12[1] = out12[2] = out12[3] = 0x00;
    out12[4] = type_;
    out12[5] = static_cast<uint8_t>((counter >> 24) & 0xFF);
    out12[6] = static_cast<uint8_t>((counter >> 16) & 0xFF);
    out12[7] = static_cast<uint8_t>((counter >> 8) & 0xFF);
    out12[8] = static_cast<uint8_t>(counter & 0xFF);
    out12[9] = out12[10] = out12[11] = 0x00;
}

} // namespace cdc::mod_lastword::wire
