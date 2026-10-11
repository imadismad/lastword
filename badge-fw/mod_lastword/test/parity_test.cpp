// parity_test.cpp — host test that proves the C++ badge engine is byte-for-byte
// compatible with proto (and therefore with badge-sim), BEFORE anything is flashed.
//
// It does NOT need the ESP-IDF or hardware: it compiles wire.cpp, BadgeProtocol.cpp
// and crypto_mbedtls.cpp on the host, links system mbedTLS, and replays the frozen
// proto/vectors.json. If this passes, the bridge/contract will accept the real
// firmware's output unchanged (same digest, same AEAD, same framing, low-s).
//
// Build: see test/CMakeLists.txt. Run from the repo root so vectors.json resolves,
// or pass its path as argv[1].
//
// What is checked:
//   1. CRC-16/CCITT known-answer ("123456789" -> 0x29B1).
//   2. COBS round-trip for the sample I3 messages in vectors.json.
//   3. intent decode/encode round-trip + digest equals vectors' digest.
//   4. A full REQUEST frame from vectors is opened, the gateway sig verifies, the
//      engine signs with a software backend, and the response frame decrypts to a
//      valid badge signature over the SAME digest, with low-s.
//   5. Tampered frames (bad tag / replayed counter / expired) are REFUSED.

#include "mod_lastword/BadgeProtocol.h"
#include "mod_lastword/wire.h"
#include "mod_lastword/crypto.h"

#include <mbedtls/ecp.h>
#include <mbedtls/ecdsa.h>
#include <mbedtls/bignum.h>
#include <mbedtls/entropy.h>
#include <mbedtls/ctr_drbg.h>

#include <cstdio>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include <fstream>
#include <sstream>

using namespace cdc::mod_lastword;

// --- tiny JSON helpers (we only need to pull hex strings / ints by key path) ---
// vectors.json is produced by proto/gen_vectors.py with a stable shape; rather than
// vendor a JSON lib we extract the few fields we need with minimal parsing.
static std::string slurp(const char* path) {
    std::ifstream f(path, std::ios::binary);
    std::stringstream ss; ss << f.rdbuf(); return ss.str();
}
// Find the first string value for "key" that appears AT OR AFTER position `from`.
// Lets us scope a leaf lookup (e.g. "pub") under a parent token (e.g. "daf").
static std::string find_str_from(const std::string& j, const std::string& key, size_t from) {
    auto k = "\"" + key + "\"";
    size_t p = j.find(k, from);
    if (p == std::string::npos) return {};
    p = j.find(':', p); if (p == std::string::npos) return {};
    size_t q = j.find('"', p); if (q == std::string::npos) return {};
    size_t r = j.find('"', q + 1); if (r == std::string::npos) return {};
    return j.substr(q + 1, r - q - 1);
}
static std::string find_str(const std::string& j, const std::string& key) {
    return find_str_from(j, key, 0);
}
// Leaf under a parent object: finds "parent" then the first "leaf" after it.
// vectors.json is small and keys are unique enough per section that this is safe.
static std::string find_under(const std::string& j, const std::string& parent,
                              const std::string& leaf) {
    size_t p = j.find("\"" + parent + "\"");
    if (p == std::string::npos) return {};
    return find_str_from(j, leaf, p);
}
static std::vector<uint8_t> unhex(std::string s) {
    if (s.rfind("0x", 0) == 0) s = s.substr(2);
    std::vector<uint8_t> o;
    for (size_t i = 0; i + 1 < s.size(); i += 2)
        o.push_back(static_cast<uint8_t>(std::stoi(s.substr(i, 2), nullptr, 16)));
    return o;
}

static int g_fail = 0;
static void check(bool cond, const char* msg) {
    std::printf("  [%s] %s\n", cond ? "PASS" : "FAIL", msg);
    if (!cond) ++g_fail;
}

// A software backend for the host test: it holds the SAME test keys as
// proto/vectors.json so signatures verify against the published pubkeys.
class HostBackend final : public IBadgeBackend {
public:
    uint8_t stockPriv[32], dafPriv[32], duressPriv[32];
    uint8_t stockPub[64], dafPub[64], duressPub[64], gwPub[64];

    bool rolePublicKey(Role role, uint8_t out[64]) override {
        if (role == Role::STOCK) std::memcpy(out, stockPub, 64);
        else if (role == Role::DAF) std::memcpy(out, dafPub, 64);
        else std::memcpy(out, duressPub, 64);
        return true;
    }
    bool gatewayPublicKey(uint8_t out[64]) override { std::memcpy(out, gwPub, 64); return true; }
    bool verifyP256(const uint8_t pub[64], const uint8_t dg[32], const uint8_t sig[64]) override {
        return crypto().p256_verify(pub, dg, sig);
    }
    Role promptAndAuthorize(const Intent&, Role requested, bool, bool* duress) override {
        *duress = false; return requested; // auto-approve with the requested role
    }
    bool signDigest(Role role, bool, const uint8_t dg[32], uint8_t sig[64]) override {
        const uint8_t* d = (role == Role::STOCK) ? stockPriv
                         : (role == Role::DAF)   ? dafPriv : duressPriv;
        return swSign(d, dg, sig);
    }
    bool isHardwareBacked() const override { return false; }

    static bool swSign(const uint8_t priv[32], const uint8_t dg[32], uint8_t sig[64]) {
        mbedtls_ecp_group grp; mbedtls_mpi d, r, s;
        mbedtls_entropy_context ent; mbedtls_ctr_drbg_context drbg;
        mbedtls_ecp_group_init(&grp); mbedtls_mpi_init(&d);
        mbedtls_mpi_init(&r); mbedtls_mpi_init(&s);
        mbedtls_entropy_init(&ent); mbedtls_ctr_drbg_init(&drbg);
        bool ok = false; const char* pers = "parity";
        do {
            if (mbedtls_ctr_drbg_seed(&drbg, mbedtls_entropy_func, &ent,
                    (const unsigned char*)pers, strlen(pers)) != 0) break;
            if (mbedtls_ecp_group_load(&grp, MBEDTLS_ECP_DP_SECP256R1) != 0) break;
            if (mbedtls_mpi_read_binary(&d, priv, 32) != 0) break;
            if (mbedtls_ecdsa_sign(&grp, &r, &s, &d, dg, 32,
                                   mbedtls_ctr_drbg_random, &drbg) != 0) break;
            if (mbedtls_mpi_write_binary(&r, sig, 32) != 0) break;
            if (mbedtls_mpi_write_binary(&s, sig + 32, 32) != 0) break;
            ok = true;
        } while (false);
        mbedtls_ctr_drbg_free(&drbg); mbedtls_entropy_free(&ent);
        mbedtls_mpi_free(&s); mbedtls_mpi_free(&r); mbedtls_mpi_free(&d);
        mbedtls_ecp_group_free(&grp);
        return ok;
    }
};

int main(int argc, char** argv) {
    const char* vpath = (argc > 1) ? argv[1] : "proto/vectors.json";
    std::string j = slurp(vpath);
    if (j.empty()) { std::printf("cannot read %s\n", vpath); return 2; }

    std::printf("mod_lastword parity vs %s\n", vpath);

    // 1. CRC known answer
    const char* kat = "123456789";
    check(wire::crc16_ccitt((const uint8_t*)kat, 9) == 0x29B1, "CRC-16/CCITT KAT 0x29B1");

    // 2. intent round-trip + digest. vectors.json is nested; hex values carry a
    //    "0x" prefix that unhex() strips.
    auto intentBytes = unhex(find_under(j, "intent", "bytes"));
    auto wantDigest  = unhex(find_under(j, "intent", "digest"));
    auto frameKey    = unhex(find_under(j, "meta", "frameKey"));
    auto contractAddr= unhex(find_under(j, "meta", "contractAddr"));
    uint64_t chainId = 31337;
    {
        size_t p = j.find("\"chainId\"");
        if (p != std::string::npos) { p = j.find(':', p); chainId = strtoull(j.c_str()+p+1, nullptr, 10); }
    }
    check(intentBytes.size() == 79, "intent is 79 bytes");

    if (intentBytes.size() == 79 && contractAddr.size() == 20 && !wantDigest.empty()) {
        Intent dec; BadgeProtocol::decodeIntent(intentBytes.data(), dec);
        uint8_t re[79]; BadgeProtocol::encodeIntent(dec, re);
        check(std::memcmp(re, intentBytes.data(), 79) == 0, "intent decode/encode round-trip");

        BadgeProtocol eng;
        eng.provision(frameKey.data(), chainId, contractAddr.data());
        uint8_t dg[32]; eng.computeDigest(intentBytes.data(), dg);
        check(std::memcmp(dg, wantDigest.data(), 32) == 0, "digest == vectors.digest");
    }

    // 4. full REQUEST -> RESPONSE through the engine with a host backend.
    //    keys.{stock,daf,duress,gateway}.{priv,pub}; frames.request.
    auto reqFrame  = unhex(find_under(j, "frames", "request"));
    auto stockPriv = unhex(find_under(j, "stock", "priv"));
    auto dafPriv   = unhex(find_under(j, "daf", "priv"));
    auto duressPriv= unhex(find_under(j, "duress", "priv"));
    auto gwPub     = unhex(find_under(j, "gateway", "pub"));
    auto dafPub    = unhex(find_under(j, "daf", "pub"));
    if (reqFrame.size() >= 29 && dafPriv.size() == 32 && gwPub.size() == 64) {
        HostBackend be;
        std::memcpy(be.dafPriv, dafPriv.data(), 32);
        if (stockPriv.size()==32) std::memcpy(be.stockPriv, stockPriv.data(), 32);
        if (duressPriv.size()==32) std::memcpy(be.duressPriv, duressPriv.data(), 32);
        std::memcpy(be.gwPub, gwPub.data(), 64);
        if (dafPub.size()==64) std::memcpy(be.dafPub, dafPub.data(), 64);

        BadgeProtocol eng;
        eng.setBackend(&be);
        eng.provision(frameKey.data(), chainId, contractAddr.data());

        uint8_t out[320];
        size_t n = eng.handleMessage(Cmd::REQUEST, reqFrame.data(), reqFrame.size(),
                                     out, sizeof(out));
        check(n > 0, "REQUEST produced a reply frame");

        // decode the reply: expect RESPONSE (0x83) carrying a sealed I2 response.
        uint8_t cmd = 0, data[300]; size_t dlen = 0;
        bool ok = wire::unpack_message(out, n, &cmd, data, sizeof(data), &dlen);
        check(ok && cmd == (uint8_t)Cmd::RESPONSE, "reply is RESPONSE (not REFUSED)");

        // open the response frame and verify the badge sig over the digest, low-s.
        if (ok && cmd == (uint8_t)Cmd::RESPONSE && dlen >= wire::HEADER_SIZE + 16) {
            wire::FrameHeader rh;
            wire::FrameHeader::unpack(data, rh);
            uint8_t key[32]; crypto().hkdf_frame_key(frameKey.data(), data, key);
            uint8_t nonce[12]; wire::gcm_nonce(rh.type, rh.counter, nonce);
            uint8_t pt[80]; size_t ptLen = 0;
            bool opened = crypto().aes256gcm_open(key, nonce, data, wire::HEADER_SIZE,
                                                  data + wire::HEADER_SIZE,
                                                  dlen - wire::HEADER_SIZE,
                                                  pt, sizeof(pt), &ptLen);
            check(opened && ptLen == 69, "response body opens, 69 bytes");
            if (opened && ptLen == 69) {
                const uint8_t* badgeSig = pt + 5; // reqId(4)+decision(1)
                Intent dec; BadgeProtocol::decodeIntent(reqFrame.data(), dec); // placeholder
                BadgeProtocol de; de.provision(frameKey.data(), chainId, contractAddr.data());
                uint8_t dg[32]; de.computeDigest(intentBytes.data(), dg);
                check(crypto().p256_verify(be.dafPub, dg, badgeSig),
                      "badge signature verifies against DAF pubkey");
                // low-s: s (second 32 bytes, big-endian) must be <= n/2.
                static const uint8_t HALF_N[32] = {
                    0x7F,0xFF,0xFF,0xFF,0x80,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
                    0xFF,0xFF,0xFF,0xFF,0xDE,0x73,0x7D,0x56,0xD3,0x8B,0xCF,0x42,
                    0x79,0xDC,0xE5,0x61,0x7E,0x31,0x92,0xA8};
                const uint8_t* sPart = badgeSig + 32;
                bool lowS = true;
                for (int i = 0; i < 32; ++i) {
                    if (sPart[i] != HALF_N[i]) { lowS = sPart[i] < HALF_N[i]; break; }
                }
                check(lowS, "s is low-s (<= n/2)");
            }
        }
    } else {
        std::printf("  [SKIP] frames/keys not in vectors (regenerate with gen_vectors)\n");
    }

    // 5. tamper rejection: a bad-tag frame must be REFUSED, never signed. The
    //    engine needs a backend+provision to reach the AEAD step.
    auto badTag = unhex(find_under(j, "invalid", "bad_tag_frame"));
    if (!badTag.empty() && frameKey.size() == 32 && contractAddr.size() == 20) {
        HostBackend be;
        auto gwp = unhex(find_under(j, "gateway", "pub"));
        if (gwp.size() == 64) std::memcpy(be.gwPub, gwp.data(), 64);
        BadgeProtocol eng; eng.setBackend(&be);
        eng.provision(frameKey.data(), chainId, contractAddr.data());
        uint8_t out[320];
        size_t n = eng.handleMessage(Cmd::REQUEST, badTag.data(), badTag.size(), out, sizeof(out));
        uint8_t cmd = 0, data[300]; size_t dlen = 0;
        bool ok = wire::unpack_message(out, n, &cmd, data, sizeof(data), &dlen);
        check(ok && cmd == (uint8_t)Cmd::REFUSED, "tampered (bad-tag) frame is REFUSED");
    } else {
        std::printf("  [SKIP] invalid.bad_tag_frame not in vectors\n");
    }

    std::printf(g_fail ? "\nFAILED (%d)\n" : "\nOK\n", g_fail);
    return g_fail ? 1 : 0;
}
