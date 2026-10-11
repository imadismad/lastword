// crypto_mbedtls.cpp — ICrypto implementation on mbedTLS. ESP-IDF bundles mbedTLS,
// and a host build links the system mbedTLS, so this one file serves both the
// device firmware and the off-device parity test. No key material is stored here.

#include "mod_lastword/crypto.h"

#include <mbedtls/sha256.h>
#include <mbedtls/hkdf.h>
#include <mbedtls/md.h>
#include <mbedtls/gcm.h>
#include <mbedtls/ecp.h>
#include <mbedtls/ecdsa.h>
#include <mbedtls/bignum.h>

#include <cstring>

namespace cdc::mod_lastword {

namespace {

class MbedCrypto final : public ICrypto {
public:
    void sha256(const uint8_t* in, size_t len, uint8_t out32[32]) override {
        mbedtls_sha256(in, len, out32, /*is224=*/0);
    }

    void hkdf_frame_key(const uint8_t frameKey32[32], const uint8_t header13[13],
                        uint8_t out32[32]) override {
        const mbedtls_md_info_t* md = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
        // salt = "" (zero-length), info = 13-byte header, ikm = 32-byte frame key.
        mbedtls_hkdf(md, nullptr, 0, frameKey32, 32, header13, 13, out32, 32);
    }

    bool aes256gcm_open(const uint8_t key32[32], const uint8_t nonce12[12],
                        const uint8_t* aad, size_t aadLen,
                        const uint8_t* ct, size_t ctLen,
                        uint8_t* pt, size_t ptCap, size_t* ptLen) override {
        if (ctLen < 16) return false;
        const size_t dataLen = ctLen - 16;
        if (dataLen > ptCap) return false;
        const uint8_t* tag = ct + dataLen;

        mbedtls_gcm_context g;
        mbedtls_gcm_init(&g);
        bool ok = false;
        if (mbedtls_gcm_setkey(&g, MBEDTLS_CIPHER_ID_AES, key32, 256) == 0) {
            int rc = mbedtls_gcm_auth_decrypt(&g, dataLen, nonce12, 12, aad, aadLen,
                                              tag, 16, ct, pt);
            ok = (rc == 0);
        }
        mbedtls_gcm_free(&g);
        if (ok) *ptLen = dataLen;
        return ok;
    }

    bool aes256gcm_seal(const uint8_t key32[32], const uint8_t nonce12[12],
                        const uint8_t* aad, size_t aadLen,
                        const uint8_t* pt, size_t ptLen,
                        uint8_t* out, size_t outCap, size_t* outLen) override {
        if (ptLen + 16 > outCap) return false;
        mbedtls_gcm_context g;
        mbedtls_gcm_init(&g);
        bool ok = false;
        if (mbedtls_gcm_setkey(&g, MBEDTLS_CIPHER_ID_AES, key32, 256) == 0) {
            uint8_t tag[16];
            int rc = mbedtls_gcm_crypt_and_tag(&g, MBEDTLS_GCM_ENCRYPT, ptLen,
                                               nonce12, 12, aad, aadLen,
                                               pt, out, 16, tag);
            if (rc == 0) {
                std::memcpy(out + ptLen, tag, 16);
                *outLen = ptLen + 16;
                ok = true;
            }
        }
        mbedtls_gcm_free(&g);
        return ok;
    }

    bool p256_verify(const uint8_t pub64[64], const uint8_t digest32[32],
                     const uint8_t sig64[64]) override {
        mbedtls_ecp_group grp;
        mbedtls_ecp_point Q;
        mbedtls_mpi r, s;
        mbedtls_ecp_group_init(&grp);
        mbedtls_ecp_point_init(&Q);
        mbedtls_mpi_init(&r);
        mbedtls_mpi_init(&s);
        bool ok = false;
        do {
            if (mbedtls_ecp_group_load(&grp, MBEDTLS_ECP_DP_SECP256R1) != 0) break;
            // Build uncompressed point 0x04 || X || Y.
            uint8_t pt[65];
            pt[0] = 0x04;
            std::memcpy(pt + 1, pub64, 64);
            if (mbedtls_ecp_point_read_binary(&grp, &Q, pt, sizeof(pt)) != 0) break;
            if (mbedtls_ecp_check_pubkey(&grp, &Q) != 0) break;
            if (mbedtls_mpi_read_binary(&r, sig64, 32) != 0) break;
            if (mbedtls_mpi_read_binary(&s, sig64 + 32, 32) != 0) break;
            ok = (mbedtls_ecdsa_verify(&grp, digest32, 32, &Q, &r, &s) == 0);
        } while (false);
        mbedtls_mpi_free(&s);
        mbedtls_mpi_free(&r);
        mbedtls_ecp_point_free(&Q);
        mbedtls_ecp_group_free(&grp);
        return ok;
    }
};

} // namespace

ICrypto& crypto() {
    static MbedCrypto inst;
    return inst;
}

} // namespace cdc::mod_lastword
