#include "TropicBackend.h"

#include "mod_lastword/crypto.h"
#include "cdc_hal/ISecureElement.h"

// Firmware services for the async e-paper + keypad approval flow.
#include "cdc_core/PinManager.h"
#include "cdc_log.h"
#include "cdc_ui/ViewStack.h"
#include "cdc_views/InfoView.h"
#include "cdc_views/PinEntryView.h"

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

// ---- async e-paper + keypad approval (non-blocking; driven by the UI task) ----
//
// beginApproval() shows the payment fields in an InfoView with Y/N callbacks and
// returns immediately. On Y we push a PinEntryView; the UI task reads the keypad.
// PinEntryView's onVerify resolves the PIN to normal/duress, onSuccess finishes
// the approval (sign + emit), onCancel/N denies. Everything runs on the UI task,
// so no serial/main-loop blocking and no deadlock.

TropicBackend* TropicBackend::s_self = nullptr;

namespace {
// Static buffers/views: the badge shows one approval at a time, and view objects
// must outlive the push (ViewStack stores pointers).
cdc::ui::InfoView     s_approveView;
cdc::ui::PinEntryView s_pinView;
char s_screen[256];
Role s_requested = Role::NONE;
bool s_duress = false;

// PinEntryView verify: true if the PIN is the badge PIN or the duress PIN. We
// record which one so finishApproval can select the duress key. Mirrors the
// cdc-badge-os AppUi unlock logic.
bool onPinVerify(const char* pin) {
    auto& pm = cdc::core::PinManager::instance();
    if (s_requested == Role::DAF && pm.hasDuressPin() && pm.isDuressPin(pin)) {
        s_duress = true;
        return true;
    }
    s_duress = false;
    return pm.verifyBadgePin(pin);
}

void onPinSuccess() {
    auto& stack = cdc::ui::ViewStack::instance();
    stack.releaseExclusive(&s_pinView);
    stack.pop(); // remove PIN view
    stack.pop(); // remove the approval InfoView
    stack.render();
    if (TropicBackend::s_self) {
        // STOCK stays STOCK, DAF stays DAF (role bits are what the contract checks);
        // duress only swaps the signing key, invisibly.
        TropicBackend::s_self->finishApproval(
            IBadgeBackend::Outcome::APPROVED, s_requested, s_duress);
    }
}

void onPinCancel() {
    auto& stack = cdc::ui::ViewStack::instance();
    stack.releaseExclusive(&s_pinView);
    stack.pop();
    stack.pop();
    stack.render();
    if (TropicBackend::s_self)
        TropicBackend::s_self->finishApproval(IBadgeBackend::Outcome::DENIED,
                                              Role::NONE, false);
}

// InfoView Y: approve -> push the PIN entry. N: deny immediately.
void onApproveYes(void* /*user*/) {
    auto& stack = cdc::ui::ViewStack::instance();
    s_pinView.init("PIN", /*maxPinLength=*/8, /*maxAttempts=*/3);
    s_pinView.setMinLength(4);
    s_pinView.setOnVerify(onPinVerify);
    s_pinView.setOnSuccess(onPinSuccess);
    s_pinView.setOnCancel(onPinCancel);
    stack.push(&s_pinView);
    stack.acquireExclusive(&s_pinView);
    stack.render();
}

void onApproveNo(void* /*user*/) {
    auto& stack = cdc::ui::ViewStack::instance();
    stack.pop(); // remove the approval InfoView
    stack.render();
    if (TropicBackend::s_self)
        TropicBackend::s_self->finishApproval(IBadgeBackend::Outcome::DENIED,
                                              Role::NONE, false);
}
} // namespace

bool TropicBackend::beginApproval(const Intent& intent, Role requested,
                                  bool softwareKey, ApprovalDone done, void* engineCtx) {
    if (pendActive_) return false; // one approval at a time
    s_self = this;
    pendDone_ = done;
    pendEngine_ = engineCtx;
    pendRequested_ = requested;
    pendActive_ = true;
    s_requested = requested;
    s_duress = false;

    const char* roleStr = (requested == Role::STOCK) ? "RESPONSABLE STOCK (simule)"
                        : (requested == Role::DAF)   ? "DAF (simule)"
                                                     : "ROLE ?";
    // Build the review screen. Addresses/amounts are what the badge RECOMPUTED and
    // will sign, never free text from the agent.
    std::snprintf(s_screen, sizeof(s_screen),
                  "%s%s\n"
                  "Benef: 0x%02x%02x..%02x%02x\n"
                  "Montant: %llu (tok#%u)\n"
                  "reqId: %lu  nonce: %lu\n"
                  "Echeance: %lu\n"
                  "[Y] approuver  [N] refuser",
                  softwareKey ? "** CLE LOGICIELLE **\n" : "",
                  roleStr,
                  intent.beneficiary[0], intent.beneficiary[1],
                  intent.beneficiary[18], intent.beneficiary[19],
                  static_cast<unsigned long long>(intent.amount), intent.token,
                  static_cast<unsigned long>(intent.reqId),
                  static_cast<unsigned long>(intent.nonce),
                  static_cast<unsigned long>(intent.deadline));

    auto& stack = cdc::ui::ViewStack::instance();
    s_approveView.init("LASTWORD", s_screen);
    s_approveView.setYesNoCallbacks(onApproveYes, onApproveNo, nullptr);
    stack.push(&s_approveView);
    stack.render();
    return true;
}

void TropicBackend::finishApproval(Outcome outcome, Role role, bool duress) {
    if (!pendActive_) return;
    pendActive_ = false;
    ApprovalDone done = pendDone_;
    void* ctx = pendEngine_;
    pendDone_ = nullptr;
    pendEngine_ = nullptr;
    if (done) done(ctx, outcome, role, duress);
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
