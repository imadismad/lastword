#include "TropicBackend.h"

#include "mod_lastword/crypto.h"
#include "cdc_hal/ISecureElement.h"

// Firmware services. For the first bring-up the approval prompt uses the serial
// Console (fields shown, PIN read) with the real PinManager duress logic. A
// polished e-paper ConfirmView + PinEntryView is a follow-up (see badge-fw/README).
#include "serial_cmd/Console.h"
#include "cdc_core/PinManager.h"
#include "cdc_log.h"

#include <mbedtls/ecp.h>
#include <mbedtls/ecdsa.h>
#include <mbedtls/bignum.h>
#include <mbedtls/entropy.h>
#include <mbedtls/ctr_drbg.h>

#include <cstdio>
#include <cstring>

namespace cdc::mod_lastword {

using cdc::hal::ISecureElement;
using cdc::hal::SeResult;
using cdc::hal::EccCurve;

static int roleIndex(Role r) {
    switch (r) {
        case Role::STOCK: return 0;
        case Role::DAF: return 1;
        case Role::RESERVED: return 2; // duress slot
        default: return -1;
    }
}

uint8_t TropicBackend::slotFor(Role role) const {
    int i = roleIndex(role);
    return static_cast<uint8_t>(slots_.eccStart + (i < 0 ? 0 : i));
}

bool TropicBackend::begin(const core::IModule::SlotRange& slots) {
    slots_ = slots;
    se_ = cdc::hal::getSecureElementInstance();
    if (!se_) { hwBacked_ = false; swFallback_ = true; }
    // Need 3 contiguous ECC slots.
    if (!slots_.hasEcc || (slots_.eccEnd - slots_.eccStart + 1) < 3) return false;
    return true;
}

static bool swGenerate(uint8_t priv[32], uint8_t pub[64]) {
    mbedtls_ecp_group grp; mbedtls_mpi d; mbedtls_ecp_point Q;
    mbedtls_entropy_context ent; mbedtls_ctr_drbg_context drbg;
    mbedtls_ecp_group_init(&grp); mbedtls_mpi_init(&d); mbedtls_ecp_point_init(&Q);
    mbedtls_entropy_init(&ent); mbedtls_ctr_drbg_init(&drbg);
    bool ok = false;
    const char* pers = "lastword-sw-key";
    do {
        if (mbedtls_ctr_drbg_seed(&drbg, mbedtls_entropy_func, &ent,
                                  reinterpret_cast<const unsigned char*>(pers),
                                  strlen(pers)) != 0) break;
        if (mbedtls_ecp_group_load(&grp, MBEDTLS_ECP_DP_SECP256R1) != 0) break;
        if (mbedtls_ecp_gen_keypair(&grp, &d, &Q, mbedtls_ctr_drbg_random, &drbg) != 0) break;
        if (mbedtls_mpi_write_binary(&d, priv, 32) != 0) break;
        // mbedTLS 3.x hides struct fields behind MBEDTLS_PRIVATE().
        if (mbedtls_mpi_write_binary(&Q.MBEDTLS_PRIVATE(X), pub, 32) != 0) break;
        if (mbedtls_mpi_write_binary(&Q.MBEDTLS_PRIVATE(Y), pub + 32, 32) != 0) break;
        ok = true;
    } while (false);
    mbedtls_ctr_drbg_free(&drbg); mbedtls_entropy_free(&ent);
    mbedtls_ecp_point_free(&Q); mbedtls_mpi_free(&d); mbedtls_ecp_group_free(&grp);
    return ok;
}

bool TropicBackend::ensureRoleKeys() {
    if (swFallback_ || !se_) {
        // software path: derive 3 keys, mark banner.
        for (int i = 0; i < 3; ++i)
            if (!swGenerate(swPriv_[i], swPub_[i])) return false;
        hwBacked_ = false;
        swFallback_ = true;
        return true;
    }
    if (!se_->sessionStart()) {
        LOG_E("LASTWORD", "ensureRoleKeys: sessionStart failed -> software fallback");
        hwBacked_ = false; swFallback_ = true; return ensureRoleKeys();
    }
    bool ok = true;
    for (int i = 0; i < 3; ++i) {
        uint8_t slot = static_cast<uint8_t>(slots_.eccStart + i);
        if (se_->eccSlotUsed(slot)) {
            // vierge badge expected: refuse to clobber an existing key.
            uint8_t pub[64];
            EccCurve c;
            SeResult rr = se_->eccGetPublicKey(slot, pub, &c);
            if (rr != SeResult::OK) {
                LOG_E("LASTWORD", "ensureRoleKeys: slot %u used but read failed (SeResult=%d)",
                      slot, (int)rr);
                ok = false; break;
            }
            LOG_I("LASTWORD", "ensureRoleKeys: slot %u already holds a key, keeping", slot);
            continue;
        }
        SeResult rg = se_->eccGenerate(slot, EccCurve::P256);
        if (rg != SeResult::OK) {
            LOG_E("LASTWORD", "ensureRoleKeys: eccGenerate(slot %u) failed (SeResult=%d)",
                  slot, (int)rg);
            ok = false; break;
        }
        LOG_I("LASTWORD", "ensureRoleKeys: generated P-256 key in slot %u", slot);
    }
    se_->sessionEnd();
    if (!ok) {
        LOG_E("LASTWORD", "ensureRoleKeys: hardware provisioning failed -> software fallback");
        hwBacked_ = false; swFallback_ = true; return ensureRoleKeys();
    }
    hwBacked_ = true;
    return true;
}

void TropicBackend::setGatewayPublicKey(const uint8_t pub64[64]) {
    std::memcpy(gatewayPub_, pub64, 64);
    gatewaySet_ = true;
}

bool TropicBackend::rolePublicKey(Role role, uint8_t out64[64]) {
    int i = roleIndex(role);
    if (i < 0) return false;
    if (swFallback_) { std::memcpy(out64, swPub_[i], 64); return true; }
    if (!se_) return false;
    if (!se_->sessionStart()) return false;
    EccCurve c;
    SeResult r = se_->eccGetPublicKey(static_cast<uint8_t>(slots_.eccStart + i), out64, &c);
    se_->sessionEnd();
    return r == SeResult::OK;
}

bool TropicBackend::gatewayPublicKey(uint8_t out64[64]) {
    if (!gatewaySet_) return false;
    std::memcpy(out64, gatewayPub_, 64);
    return true;
}

bool TropicBackend::verifyP256(const uint8_t pub64[64], const uint8_t digest[32],
                               const uint8_t sig64[64]) {
    return crypto().p256_verify(pub64, digest, sig64);
}

// ---- display + PIN. Thin wrappers over the firmware UI; adapted in the fork. ----
Role TropicBackend::promptAndAuthorize(const Intent& intent, Role requested,
                                       bool softwareKey, bool* duress) {
    *duress = false;

    char line1[48];
    const char* roleStr = (requested == Role::STOCK) ? "RESPONSABLE STOCK (simule)"
                        : (requested == Role::DAF)   ? "DAF (simule)"
                                                     : "ROLE?";
    std::snprintf(line1, sizeof(line1), "ROLE : %s", roleStr);

    char benef[32];
    std::snprintf(benef, sizeof(benef), "benef 0x%02x%02x..%02x%02x",
                  intent.beneficiary[0], intent.beneficiary[1],
                  intent.beneficiary[18], intent.beneficiary[19]);
    char amount[40];
    std::snprintf(amount, sizeof(amount), "montant %llu (tok#%u)",
                  static_cast<unsigned long long>(intent.amount), intent.token);

    // First bring-up UX: show the fields and read the PIN over the serial Console.
    // (The e-paper ConfirmView + PinEntryView flow is a documented follow-up; it
    // does not change what is signed or the duress semantics below.)
    using cdc::serial::Console;
    Console::printf("\r\n==== LASTWORD approval ====\r\n");
    if (softwareKey) Console::printf("  [SOFTWARE KEY - hardware guarantee NOT demonstrated]\r\n");
    Console::printf("  %s\r\n", line1);
    Console::printf("  %s\r\n", benef);
    Console::printf("  %s\r\n", amount);
    Console::printf("  deadline %lu  reqId %lu\r\n",
                    static_cast<unsigned long>(intent.deadline),
                    static_cast<unsigned long>(intent.reqId));
    Console::printf("  enter PIN then NEWLINE (empty = refuse): ");

    char pin[cdc::core::PinManager::PIN_MAX + 1] = {};
    size_t pl = 0;
    for (;;) {
        int c = Console::getchar();
        if (c < 0) continue;                       // non-blocking: spin until input
        if (c == '\r' || c == '\n') break;
        if (c == 0x08 || c == 0x7F) {              // backspace
            if (pl) --pl;
            continue;
        }
        if (pl < sizeof(pin) - 1) pin[pl++] = static_cast<char>(c);
    }
    pin[pl] = '\0';
    if (pl == 0) { Console::printf("refused\r\n"); return Role::NONE; }

    // Real duress logic (mirrors cdc-badge-os AppUi unlock): a duress PIN takes the
    // duress path (same outward behaviour, caller stays DAF); otherwise the badge
    // PIN approves. The chip has one badge PIN + one duress PIN, so the stock/DAF
    // split is enforced by the signed role bits, not by distinct PINs.
    auto& pm = cdc::core::PinManager::instance();
    if (requested == Role::DAF && pm.hasDuressPin() && pm.isDuressPin(pin)) {
        *duress = true;
        return Role::DAF;
    }
    if (pm.verifyBadgePin(pin)) {
        return requested; // STOCK stays STOCK, DAF stays DAF (role bits are signed)
    }
    Console::printf("wrong PIN\r\n");
    return Role::NONE;
}

bool TropicBackend::signDigest(Role role, bool duress, const uint8_t digest[32],
                               uint8_t sig64[64]) {
    // duress on the DAF role selects the duress key slot/index.
    int i = (role == Role::DAF && duress) ? 2 : roleIndex(role);
    if (i < 0) return false;

    if (swFallback_) {
        // software ECDSA over the pre-hashed digest.
        mbedtls_ecp_group grp; mbedtls_mpi d, r, s;
        mbedtls_entropy_context ent; mbedtls_ctr_drbg_context drbg;
        mbedtls_ecp_group_init(&grp); mbedtls_mpi_init(&d);
        mbedtls_mpi_init(&r); mbedtls_mpi_init(&s);
        mbedtls_entropy_init(&ent); mbedtls_ctr_drbg_init(&drbg);
        bool ok = false;
        const char* pers = "lastword-sw-sign";
        do {
            if (mbedtls_ctr_drbg_seed(&drbg, mbedtls_entropy_func, &ent,
                    reinterpret_cast<const unsigned char*>(pers), strlen(pers)) != 0) break;
            if (mbedtls_ecp_group_load(&grp, MBEDTLS_ECP_DP_SECP256R1) != 0) break;
            if (mbedtls_mpi_read_binary(&d, swPriv_[i], 32) != 0) break;
            if (mbedtls_ecdsa_sign(&grp, &r, &s, &d, digest, 32,
                                   mbedtls_ctr_drbg_random, &drbg) != 0) break;
            if (mbedtls_mpi_write_binary(&r, sig64, 32) != 0) break;
            if (mbedtls_mpi_write_binary(&s, sig64 + 32, 32) != 0) break;
            ok = true;
        } while (false);
        mbedtls_ctr_drbg_free(&drbg); mbedtls_entropy_free(&ent);
        mbedtls_mpi_free(&s); mbedtls_mpi_free(&r); mbedtls_mpi_free(&d);
        mbedtls_ecp_group_free(&grp);
        return ok;
    }

    if (!se_) return false;
    if (!se_->sessionStart()) return false;
    size_t sigLen = 0;
    // IMPORTANT: ecdsaSignDigest, NOT ecdsaSign — the digest is already SHA-256,
    // it must not be hashed again (would break the contract's recomputed digest).
    SeResult r = se_->ecdsaSignDigest(static_cast<uint8_t>(slots_.eccStart + i),
                                      digest, sig64, &sigLen);
    se_->sessionEnd();
    return r == SeResult::OK && sigLen == 64;
}

} // namespace cdc::mod_lastword
