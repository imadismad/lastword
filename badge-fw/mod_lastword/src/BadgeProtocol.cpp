#include "mod_lastword/BadgeProtocol.h"
#include "mod_lastword/wire.h"
#include "mod_lastword/crypto.h"

#include <cstring>

namespace cdc::mod_lastword {

using namespace cdc::mod_lastword::wire;

// P-256 curve order n, for the low-s normalization (matches proto P256_N).
static const uint8_t P256_N[32] = {
    0xFF,0xFF,0xFF,0xFF,0x00,0x00,0x00,0x00,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,
    0xBC,0xE6,0xFA,0xAD,0xA7,0x17,0x9E,0x84,0xF3,0xB9,0xCA,0xC2,0xFC,0x63,0x25,0x51};

// Compare big-endian 32-byte ints: returns true if a > b.
static bool gt256(const uint8_t a[32], const uint8_t b[32]) {
    for (int i = 0; i < 32; ++i) {
        if (a[i] != b[i]) return a[i] > b[i];
    }
    return false;
}
// out = n - s (big-endian), used when s > n/2.
static void sub256(const uint8_t n[32], const uint8_t s[32], uint8_t out[32]) {
    int borrow = 0;
    for (int i = 31; i >= 0; --i) {
        int v = static_cast<int>(n[i]) - s[i] - borrow;
        if (v < 0) { v += 256; borrow = 1; } else { borrow = 0; }
        out[i] = static_cast<uint8_t>(v);
    }
}
// n/2 (floor), big-endian, computed once.
static void half_n(uint8_t out[32]) {
    uint8_t carry = 0;
    for (int i = 0; i < 32; ++i) {
        uint8_t v = P256_N[i];
        out[i] = static_cast<uint8_t>((carry << 7) | (v >> 1));
        carry = v & 1;
    }
}
// Normalize s in place to low-s form (s := n - s if s > n/2).
static void normalize_low_s(uint8_t s[32]) {
    uint8_t h[32];
    half_n(h);
    if (gt256(s, h)) {
        uint8_t tmp[32];
        sub256(P256_N, s, tmp);
        std::memcpy(s, tmp, 32);
    }
}

// ----- intent codec (I1), big-endian, mirrors intent.py _STRUCT ----------------
bool BadgeProtocol::decodeIntent(const uint8_t in[79], Intent& o) {
    size_t p = 0;
    o.version = in[p++];
    o.algorithm = in[p++];
    o.reqId = (static_cast<uint32_t>(in[p]) << 24) | (static_cast<uint32_t>(in[p+1]) << 16) |
              (static_cast<uint32_t>(in[p+2]) << 8) | in[p+3]; p += 4;
    std::memcpy(o.beneficiary, in + p, 20); p += 20;
    o.token = in[p++];
    o.amount = 0;
    for (int i = 0; i < 8; ++i) o.amount = (o.amount << 8) | in[p++];
    o.nonce = (static_cast<uint32_t>(in[p]) << 24) | (static_cast<uint32_t>(in[p+1]) << 16) |
              (static_cast<uint32_t>(in[p+2]) << 8) | in[p+3]; p += 4;
    o.deadline = (static_cast<uint32_t>(in[p]) << 24) | (static_cast<uint32_t>(in[p+1]) << 16) |
                 (static_cast<uint32_t>(in[p+2]) << 8) | in[p+3]; p += 4;
    std::memcpy(o.quoteHash, in + p, 32); p += 32;
    o.flags = static_cast<uint16_t>((in[p] << 8) | in[p+1]); p += 2;
    o.policy = static_cast<uint16_t>((in[p] << 8) | in[p+1]); p += 2;
    return p == 79;
}

void BadgeProtocol::encodeIntent(const Intent& in, uint8_t out[79]) {
    size_t p = 0;
    out[p++] = in.version;
    out[p++] = in.algorithm;
    out[p++] = static_cast<uint8_t>((in.reqId >> 24) & 0xFF);
    out[p++] = static_cast<uint8_t>((in.reqId >> 16) & 0xFF);
    out[p++] = static_cast<uint8_t>((in.reqId >> 8) & 0xFF);
    out[p++] = static_cast<uint8_t>(in.reqId & 0xFF);
    std::memcpy(out + p, in.beneficiary, 20); p += 20;
    out[p++] = in.token;
    for (int i = 7; i >= 0; --i) out[p++] = static_cast<uint8_t>((in.amount >> (i * 8)) & 0xFF);
    out[p++] = static_cast<uint8_t>((in.nonce >> 24) & 0xFF);
    out[p++] = static_cast<uint8_t>((in.nonce >> 16) & 0xFF);
    out[p++] = static_cast<uint8_t>((in.nonce >> 8) & 0xFF);
    out[p++] = static_cast<uint8_t>(in.nonce & 0xFF);
    out[p++] = static_cast<uint8_t>((in.deadline >> 24) & 0xFF);
    out[p++] = static_cast<uint8_t>((in.deadline >> 16) & 0xFF);
    out[p++] = static_cast<uint8_t>((in.deadline >> 8) & 0xFF);
    out[p++] = static_cast<uint8_t>(in.deadline & 0xFF);
    std::memcpy(out + p, in.quoteHash, 32); p += 32;
    out[p++] = static_cast<uint8_t>((in.flags >> 8) & 0xFF);
    out[p++] = static_cast<uint8_t>(in.flags & 0xFF);
    out[p++] = static_cast<uint8_t>((in.policy >> 8) & 0xFF);
    out[p++] = static_cast<uint8_t>(in.policy & 0xFF);
}

void BadgeProtocol::computeDigest(const uint8_t intent79[79], uint8_t out32[32]) const {
    // SHA-256( "LASTWORD-v1" || chainId(8 BE) || contractAddr(20) || intent(79) )
    uint8_t pre[11 + 8 + 20 + 79];
    size_t p = 0;
    static const char tag[11] = {'L','A','S','T','W','O','R','D','-','v','1'};
    std::memcpy(pre + p, tag, 11); p += 11;
    for (int i = 7; i >= 0; --i) pre[p++] = static_cast<uint8_t>((chainId_ >> (i * 8)) & 0xFF);
    std::memcpy(pre + p, contractAddr_, 20); p += 20;
    std::memcpy(pre + p, intent79, 79); p += 79;
    crypto().sha256(pre, p, out32);
}

void BadgeProtocol::provision(const uint8_t frameKey[32], uint64_t chainId,
                              const uint8_t contractAddr[20]) {
    std::memcpy(frameKey_, frameKey, 32);
    chainId_ = chainId;
    std::memcpy(contractAddr_, contractAddr, 20);
    provisioned_ = true;
}

size_t BadgeProtocol::emitRefused(Refuse reason, uint8_t* out, size_t outCap) {
    uint8_t code = static_cast<uint8_t>(reason);
    return pack_message(static_cast<uint8_t>(Cmd::REFUSED), &code, 1, out, outCap);
}

size_t BadgeProtocol::handleMessage(Cmd cmd, const uint8_t* data, size_t len,
                                    uint8_t* out, size_t outCap) {
    if (!backend_) return emitRefused(Refuse::OTHER, out, outCap);

    switch (cmd) {
    case Cmd::HELLO: {
        // HELLO_OK: stock(64) || daf(64) || duress(64)
        uint8_t blob[192];
        if (!backend_->rolePublicKey(Role::STOCK, blob) ||
            !backend_->rolePublicKey(Role::DAF, blob + 64) ||
            !backend_->rolePublicKey(Role::RESERVED, blob + 128)) { // RESERVED slot = duress
            return emitRefused(Refuse::NOT_PROVISIONED, out, outCap);
        }
        return pack_message(static_cast<uint8_t>(Cmd::HELLO_OK), blob, sizeof(blob), out, outCap);
    }
    case Cmd::PROVISION: {
        // frameKey(32) || chainId(8 BE) || contractAddr(20) || gatewayPub(64) = 124
        if (len != 124) return emitRefused(Refuse::OTHER, out, outCap);
        uint64_t cid = 0;
        for (int i = 0; i < 8; ++i) cid = (cid << 8) | data[32 + i];
        provision(data, cid, data + 40);
        // Install the gateway public key so handleRequest can verify the request
        // signature before displaying anything.
        backend_->setGatewayPublicKey(data + 60);
        return pack_message(static_cast<uint8_t>(Cmd::PROV_OK), nullptr, 0, out, outCap);
    }
    case Cmd::REQUEST:
        return handleRequest(data, len, out, outCap);
    default:
        return emitRefused(Refuse::OTHER, out, outCap);
    }
}

size_t BadgeProtocol::handleRequest(const uint8_t* frame, size_t len,
                                    uint8_t* out, size_t outCap) {
    if (!provisioned_) return emitRefused(Refuse::NOT_PROVISIONED, out, outCap);

    // 1. parse + verify the I2 clear header, derive the per-message key, open AEAD.
    if (len < HEADER_SIZE + 16) return emitRefused(Refuse::BAD_AEAD, out, outCap);
    FrameHeader hdr;
    if (!FrameHeader::unpack(frame, hdr)) return emitRefused(Refuse::BAD_AEAD, out, outCap);
    if (hdr.type != TYPE_REQUEST) return emitRefused(Refuse::BAD_AEAD, out, outCap);

    uint8_t key[32];
    crypto().hkdf_frame_key(frameKey_, frame /*13-byte header*/, key);
    uint8_t nonce[12];
    gcm_nonce(hdr.type, hdr.counter, nonce);

    uint8_t pt[160];
    size_t ptLen = 0;
    if (!crypto().aes256gcm_open(key, nonce, frame, HEADER_SIZE,
                                 frame + HEADER_SIZE, len - HEADER_SIZE,
                                 pt, sizeof(pt), &ptLen)) {
        return emitRefused(Refuse::BAD_AEAD, out, outCap);
    }
    if (ptLen != 143 || hdr.bodyLen != 143) return emitRefused(Refuse::BAD_AEAD, out, outCap);

    // request body = intent(79) || gatewaySig(64)
    const uint8_t* intentBytes = pt;
    const uint8_t* gatewaySig = pt + 79;

    // 2. recompute the digest from the DECODED fields (never trust free text).
    Intent intent;
    if (!decodeIntent(intentBytes, intent)) return emitRefused(Refuse::BAD_AEAD, out, outCap);
    uint8_t digest[32];
    computeDigest(intentBytes, digest);

    // 3. verify the gateway signature over the digest BEFORE displaying anything.
    uint8_t gpub[64];
    if (!backend_->gatewayPublicKey(gpub) ||
        !backend_->verifyP256(gpub, digest, gatewaySig)) {
        return emitRefused(Refuse::BAD_GATEWAY_SIG, out, outCap);
    }

    // 4. ASYNC: begin a human approval and return with no reply now. The badge
    //    shows the fields on the e-paper and reads the PIN on the keypad via the
    //    UI task; blocking here would freeze that task and deadlock. When the user
    //    decides, the backend calls onApprovalDone(), which signs (on approve) and
    //    emits the RESPONSE/REFUSED frame via the sink captured in feedByte().
    if (pending_) {
        // A prior approval is still on screen; refuse the new one rather than
        // clobbering the pending state.
        return emitRefused(Refuse::OTHER, out, outCap);
    }
    std::memcpy(pendDigest_, digest, 32);
    pendReqId_ = intent.reqId;
    pendBadgeId_ = hdr.badgeId;
    pending_ = true;

    Role requested = intent.role();
    if (!backend_->beginApproval(intent, requested, !backend_->isHardwareBacked(),
                                 &BadgeProtocol::onApprovalDone, this)) {
        pending_ = false;
        return emitRefused(Refuse::OTHER, out, outCap);
    }
    return 0; // no immediate reply; the response is deferred to onApprovalDone
}

size_t BadgeProtocol::buildResponse(const uint8_t sig64[64], uint32_t reqId,
                                    uint32_t badgeId, uint8_t* out, size_t outCap) {
    // body = reqId(4) || decision(1=approve) || badgeSig(64)
    uint8_t body[69];
    body[0] = static_cast<uint8_t>((reqId >> 24) & 0xFF);
    body[1] = static_cast<uint8_t>((reqId >> 16) & 0xFF);
    body[2] = static_cast<uint8_t>((reqId >> 8) & 0xFF);
    body[3] = static_cast<uint8_t>(reqId & 0xFF);
    body[4] = 0x01; // approve
    std::memcpy(body + 5, sig64, 64);

    ++respCounter_;
    FrameHeader rh;
    rh.version = 1;
    rh.type = TYPE_RESPONSE;
    rh.badgeId = badgeId;
    rh.counter = respCounter_;
    rh.bodyLen = sizeof(body);
    uint8_t rhdr[HEADER_SIZE];
    rh.pack(rhdr);

    uint8_t rkey[32];
    crypto().hkdf_frame_key(frameKey_, rhdr, rkey);
    uint8_t rnonce[12];
    gcm_nonce(rh.type, rh.counter, rnonce);

    uint8_t sealed[HEADER_SIZE + 69 + 16];
    std::memcpy(sealed, rhdr, HEADER_SIZE);
    size_t ctLen = 0;
    if (!crypto().aes256gcm_seal(rkey, rnonce, rhdr, HEADER_SIZE, body, sizeof(body),
                                 sealed + HEADER_SIZE, sizeof(sealed) - HEADER_SIZE, &ctLen)) {
        return 0;
    }
    return pack_message(static_cast<uint8_t>(Cmd::RESPONSE), sealed, HEADER_SIZE + ctLen,
                        out, outCap);
}

void BadgeProtocol::onApprovalDone(void* engineCtx, IBadgeBackend::Outcome outcome,
                                   Role role, bool duress) {
    auto* self = static_cast<BadgeProtocol*>(engineCtx);
    if (!self->pending_) return; // stale completion; ignore
    self->pending_ = false;

    uint8_t out[300];
    size_t n = 0;

    if (outcome == IBadgeBackend::Outcome::APPROVED) {
        uint8_t sig[64];
        if (self->backend_ && self->backend_->signDigest(role, duress, self->pendDigest_, sig)) {
            normalize_low_s(sig + 32); // s is the second half
            n = self->buildResponse(sig, self->pendReqId_, self->pendBadgeId_, out, sizeof(out));
            if (n == 0) n = self->emitRefused(Refuse::OTHER, out, sizeof(out));
        } else {
            n = self->emitRefused(Refuse::OTHER, out, sizeof(out));
        }
    } else {
        Refuse r = (outcome == IBadgeBackend::Outcome::EXPIRED) ? Refuse::EXPIRED
                                                                : Refuse::USER_REFUSED;
        n = self->emitRefused(r, out, sizeof(out));
    }

    if (n && self->deferredSink_) {
        self->deferredSink_(self->deferredCtx_, out, n);
    }
}

bool BadgeProtocol::feedByte(uint8_t b, ByteSink sink, void* ctx) {
    if (rxLen_ < RX_MAX) rx_[rxLen_++] = b;
    if (b != 0x00) {
        if (rxLen_ >= RX_MAX) rxLen_ = 0; // overrun: resync on next delimiter
        return false;
    }
    // complete COBS frame (ends on this 0x00)
    uint8_t cmd = 0, data[260];
    size_t dataLen = 0;
    bool ok = unpack_message(rx_, rxLen_, &cmd, data, sizeof(data), &dataLen);
    rxLen_ = 0;
    if (!ok) return false;

    // Capture the sink so a deferred async approval (REQUEST -> human PIN) can emit
    // its RESPONSE/REFUSED on the same transport once the user decides.
    deferredSink_ = sink;
    deferredCtx_ = ctx;

    uint8_t resp[300];
    size_t n = handleMessage(static_cast<Cmd>(cmd), data, dataLen, resp, sizeof(resp));
    // handleMessage returns 0 for a REQUEST that is now pending human approval
    // (the reply will come later via onApprovalDone -> deferredSink_). For all
    // other messages (HELLO/PROVISION, or an early rejection) it returns the frame
    // to send right now.
    if (n && sink) sink(ctx, resp, n);
    return n != 0;
}

} // namespace cdc::mod_lastword
