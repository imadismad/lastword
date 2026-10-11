#pragma once

// crypto.h — the small crypto surface the protocol engine needs, behind a provider
// interface so the exact same engine runs on-device (ESP-IDF mbedTLS) and in the
// host parity test. All of these are standard, interoperable primitives; the point
// of the interface is only to pick the available library at build time.
//
// Implemented in crypto_mbedtls.cpp (works on both ESP-IDF and a host with mbedTLS).

#include <cstddef>
#include <cstdint>

namespace cdc::mod_lastword {

class ICrypto {
public:
    virtual ~ICrypto() = default;

    // SHA-256 over `in` -> out32.
    virtual void sha256(const uint8_t* in, size_t len, uint8_t out32[32]) = 0;

    // HKDF-SHA256(ikm=frameKey32, salt="", info=header13) -> out32. Mirrors
    // proto hkdf_frame_key(). (I2 per-message key.)
    virtual void hkdf_frame_key(const uint8_t frameKey32[32],
                                const uint8_t header13[13], uint8_t out32[32]) = 0;

    // AES-256-GCM decrypt. key32, 12-byte nonce, aad (the 13-byte header), ct is
    // ciphertext||tag(16). Writes plaintext to `pt` (cap ptCap), sets *ptLen.
    // Returns true only if the tag verifies.
    virtual bool aes256gcm_open(const uint8_t key32[32], const uint8_t nonce12[12],
                                const uint8_t* aad, size_t aadLen,
                                const uint8_t* ct, size_t ctLen,
                                uint8_t* pt, size_t ptCap, size_t* ptLen) = 0;

    // AES-256-GCM encrypt. Writes ciphertext||tag(16) to `out` (cap outCap), sets
    // *outLen = ptLen + 16. Returns false on overflow.
    virtual bool aes256gcm_seal(const uint8_t key32[32], const uint8_t nonce12[12],
                                const uint8_t* aad, size_t aadLen,
                                const uint8_t* pt, size_t ptLen,
                                uint8_t* out, size_t outCap, size_t* outLen) = 0;

    // Verify an ECDSA P-256 signature (r||s, 64 bytes) over a 32-byte digest with a
    // 64-byte uncompressed public key (X||Y). Treats the digest as pre-hashed.
    // Used ONLY for the gateway-signature check (the badge's own signing goes
    // through the secure element, not here).
    virtual bool p256_verify(const uint8_t pub64[64], const uint8_t digest32[32],
                             const uint8_t sig64[64]) = 0;
};

// Returns the process-wide crypto provider (mbedTLS-backed).
ICrypto& crypto();

} // namespace cdc::mod_lastword
