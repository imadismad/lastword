#include "TropicBackend.h"

#include "mod_lastword/crypto.h"
#include "cdc_hal/ISecureElement.h"

// Firmware UI + input. These headers come from cdc-badge-os; the exact view API
// is adapted in the fork (see badge-fw/README.md "UI integration"). The calls are
// wrapped in small helpers so a UI API change touches only this file.
#include "cdc_os_ui/AppUi.h"
#include "cdc_core/PinManager.h"

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
        if (mbedtls_mpi_write_binary(&Q.X, pub, 32) != 0) break;
        if (mbedtls_mpi_write_binary(&Q.Y, pub + 32, 32) != 0) break;
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
    if (!se_->sessionStart()) { hwBacked_ = false; swFallback_ = true; return ensureRoleKeys(); }
    bool ok = true;
    for (int i = 0; i < 3; ++i) {
        uint8_t slot = static_cast<uint8_t>(slots_.eccStart + i);
        if (se_->eccSlotUsed(slot)) {
            // vierge badge expected: refuse to clobber an existing key.
            uint8_t pub[64];
            EccCurve c;
            if (se_->eccGetPublicKey(slot, pub, &c) != SeResult::OK) { ok = false; break; }
            // slot already holds our key from a previous boot -> fine, keep it.
            continue;
        }
        if (se_->eccGenerate(slot, EccCurve::P256) != SeResult::OK) { ok = false; break; }
    }
    se_->sessionEnd();
    if (!ok) { hwBacked_ = false; swFallback_ = true; return ensureRoleKeys(); }
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

    // AppUi::showApprovalScreen renders the banner + fields on the e-paper and,
    // when softwareKey is true, keeps a permanent "SOFTWARE KEY" line (so the
    // hardware guarantee is never silently implied). Returns the PIN string or
    // empty on cancel. (Signature adapted in the fork patch.)
    char pin[cdc::core::PinManager::PIN_MAX + 1] = {};
    bool approved = cdc::ui::AppUi::instance().showApprovalScreen(
        line1, benef, amount, intent.deadline, softwareKey, pin, sizeof(pin));
    if (!approved || pin[0] == '\0') return Role::NONE;

    // Map PIN -> role/key via PinManager. The DAF duress PIN resolves to the duress
    // key but keeps the DAF role so the response frame is indistinguishable.
    auto& pm = cdc::core::PinManager::instance();
    if (requested == Role::STOCK) {
        return pm.verifyRolePin("stock", pin) ? Role::STOCK : Role::NONE;
    }
    if (requested == Role::DAF) {
        if (pm.verifyRolePin("daf", pin)) return Role::DAF;
        if (pm.verifyDuressPin(pin)) { *duress = true; return Role::DAF; }
        return Role::NONE;
    }
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
