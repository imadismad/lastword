#pragma once

// BadgeProtocol — transport- and hardware-agnostic I3 engine for the badge side.
//
// This is the C++ mirror of badge-sim/badge_sim.py's BadgeSim.handle(). It owns NO
// hardware: it is driven by raw COBS frames (handleFrame) and delegates signing,
// display and PIN entry to the IBadgeBackend. That split lets the exact same engine
// run on-device (TROPIC01 backend) and off-device in a host test that replays
// proto/vectors.json (software backend), guaranteeing byte-for-byte parity with the
// Python simulator — which is what makes the bridge/contract accept the real badge
// unchanged.
//
// Wire formats come from proto/SPEC.md:
//   I1 intent  : 79 bytes, big-endian fields.
//   I2 frame   : 13-byte clear header + AES-256-GCM(body) + 16-byte tag.
//   I3 message : COBS( cmd(1) | len(2 BE) | data | crc16-ccitt(2 BE) ) + 0x00.
//   digest     : SHA-256("LASTWORD-v1" || chainId(8 BE) || contractAddr(20) || intent(79)).

#include <cstddef>
#include <cstdint>

namespace cdc::mod_lastword {

// I3 command codes (proto/SPEC.md I3).
enum class Cmd : uint8_t {
    HELLO     = 0x01,
    PROVISION = 0x02,
    REQUEST   = 0x03,
    HELLO_OK  = 0x81,
    PROV_OK   = 0x82,
    RESPONSE  = 0x83,
    REFUSED   = 0x84,
};

// REFUSED reason codes (proto/SPEC.md I3).
enum class Refuse : uint8_t {
    BAD_GATEWAY_SIG = 0x01,
    BAD_AEAD        = 0x02,
    USER_REFUSED    = 0x03,
    EXPIRED         = 0x04,
    NOT_PROVISIONED = 0x05,
    OTHER           = 0xFF,
};

// Role encoded in intent.flags bits 0-1 (proto/SPEC.md I1).
enum class Role : uint8_t { NONE = 0, STOCK = 1, DAF = 2, RESERVED = 3 };

// Decoded 79-byte intent. Mirrors proto/src/lastword_proto/intent.py.
struct Intent {
    uint8_t  version;
    uint8_t  algorithm;
    uint32_t reqId;
    uint8_t  beneficiary[20];
    uint8_t  token;
    uint64_t amount;
    uint32_t nonce;
    uint32_t deadline;
    uint8_t  quoteHash[32];
    uint16_t flags;
    uint16_t policy;

    Role role() const { return static_cast<Role>(flags & 0x0003); }
};

// Backend the engine depends on. On-device: TropicBackend (TROPIC01 + e-paper +
// keypad). Host test: a software implementation driven by vectors.json.
class IBadgeBackend {
public:
    virtual ~IBadgeBackend() = default;

    // The 3 role public keys, uncompressed X||Y (64 bytes each), for HELLO_OK.
    // Returns false if the badge is not yet provisioned with keys.
    virtual bool rolePublicKey(Role role, uint8_t out64[64]) = 0;

    // Gateway public key (installed at provisioning) used to verify the request
    // signature before anything is displayed. 64 bytes X||Y.
    virtual bool gatewayPublicKey(uint8_t out64[64]) = 0;

    // Verify a P-256 signature (r||s, 64 bytes) over a 32-byte digest with the
    // given 64-byte public key. Used only for the gateway check.
    virtual bool verifyP256(const uint8_t pub64[64], const uint8_t digest[32],
                            const uint8_t sig64[64]) = 0;

    // Show the role banner + economic fields on the e-paper and block for the
    // user's PIN on the keypad. Returns which key the entered PIN unlocks:
    //   Role::STOCK / Role::DAF for the normal flow,
    //   Role::DAF with *duress=true when the duress PIN was entered (same screen,
    //     identical outward behaviour — the response frame must not reveal it),
    //   Role::NONE if the user refused or the PIN was wrong.
    // `softwareKey` makes the display show the permanent "SOFTWARE KEY" banner.
    virtual Role promptAndAuthorize(const Intent& intent, Role requested,
                                    bool softwareKey, bool* duress) = 0;

    // Sign a 32-byte digest with the role's key. On-device this calls
    // ISecureElement::ecdsaSignDigest on the role's TROPIC01 slot (no re-hash);
    // the fallback uses a software P-256 key. The engine normalizes s to low-s
    // afterwards, so the backend may return any valid s.
    // `duress` selects the duress key for the DAF role.
    // Returns false on any signing error. sig64 = r||s.
    virtual bool signDigest(Role role, bool duress, const uint8_t digest[32],
                            uint8_t sig64[64]) = 0;

    // True when signDigest/rolePublicKey are backed by the TROPIC01 (hardware),
    // false when the software fallback is active (controls the e-paper banner).
    virtual bool isHardwareBacked() const = 0;
};

class BadgeProtocol {
public:
    void setBackend(IBadgeBackend* backend) { backend_ = backend; }

    // Installs frame key / chainId / contract address (set by PROVISION, or by a
    // host test directly). Needed to open frames and recompute the digest.
    void provision(const uint8_t frameKey[32], uint64_t chainId,
                   const uint8_t contractAddr[20]);
    bool isProvisioned() const { return provisioned_; }

    // Handle one decoded I3 message (cmd + payload, CRC already checked by the
    // COBS layer). Writes a framed reply into `out` (COBS-encoded, 0x00-terminated)
    // and returns its length, or 0 on a framing error. `outCap` is the capacity.
    size_t handleMessage(Cmd cmd, const uint8_t* data, size_t len,
                         uint8_t* out, size_t outCap);

    // Convenience: feed raw bytes; when a full COBS frame (0x00) is assembled it
    // is decoded, CRC-checked, dispatched through handleMessage, and the reply is
    // emitted via the sink. Returns true if a frame was processed.
    using ByteSink = void (*)(void* ctx, const uint8_t* bytes, size_t n);
    bool feedByte(uint8_t b, ByteSink sink, void* ctx);

    // --- exposed for unit tests (host) --------------------------------------
    static bool decodeIntent(const uint8_t in79[79], Intent& out);
    static void encodeIntent(const Intent& in, uint8_t out79[79]);
    // digest = SHA-256(domain || chainId || contractAddr || intent)
    void computeDigest(const uint8_t intent79[79], uint8_t out32[32]) const;

private:
    size_t handleRequest(const uint8_t* frame, size_t len, uint8_t* out, size_t outCap);
    size_t emitRefused(Refuse reason, uint8_t* out, size_t outCap);

    IBadgeBackend* backend_ = nullptr;

    bool     provisioned_ = false;
    uint8_t  frameKey_[32] = {};
    uint64_t chainId_ = 0;
    uint8_t  contractAddr_[20] = {};
    uint32_t respCounter_ = 1000; // response frame counter (anti-replay, like the sim)

    // COBS reassembly buffer for feedByte().
    static constexpr size_t RX_MAX = 300;
    uint8_t rx_[RX_MAX];
    size_t  rxLen_ = 0;
};

} // namespace cdc::mod_lastword
