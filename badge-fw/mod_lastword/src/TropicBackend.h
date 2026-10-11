#pragma once

// TropicBackend — on-device IBadgeBackend. Signs with the TROPIC01 via the
// firmware's ISecureElement (hardware root of trust), falls back to a software
// P-256 key only if the chip cannot sign, and drives the e-paper + keypad for the
// role banner and PIN entry. This is the ONLY place that talks to hardware; the
// protocol engine (BadgeProtocol) stays pure.
//
// Hard rules honoured here (cahier des charges s16ter/s17): we only call
// eccGenerate / eccGetPublicKey / ecdsaSignDigest on OUR OWN assigned slots, we
// never touch pairing-key slots or I-Config, and we refuse to overwrite a slot
// that is already occupied (defensive: a vierge badge is expected).

#include "mod_lastword/BadgeProtocol.h"
#include "cdc_core/IModule.h"

#include <cstdint>

namespace cdc::hal { class ISecureElement; }

namespace cdc::mod_lastword {

class TropicBackend final : public IBadgeBackend {
public:
    // `slots` is the ECC range assigned to mod_lastword by the firmware slot map.
    // We map: eccStart+0 = stock, +1 = DAF, +2 = duress.
    bool begin(const core::IModule::SlotRange& slots);

    // Generate the 3 role keys in-chip IF the slots are empty (first boot on a
    // vierge badge). Returns false and does nothing if any target slot is already
    // occupied (we never erase someone else's key). Also installs the gateway
    // public key (provisioned from the host) — see setGatewayPublicKey.
    bool ensureRoleKeys();

    void setGatewayPublicKey(const uint8_t pub64[64]);

    // IBadgeBackend
    bool rolePublicKey(Role role, uint8_t out64[64]) override;
    bool gatewayPublicKey(uint8_t out64[64]) override;
    bool verifyP256(const uint8_t pub64[64], const uint8_t digest[32],
                    const uint8_t sig64[64]) override;
    Role promptAndAuthorize(const Intent& intent, Role requested,
                            bool softwareKey, bool* duress) override;
    bool signDigest(Role role, bool duress, const uint8_t digest[32],
                    uint8_t sig64[64]) override;
    bool isHardwareBacked() const override { return hwBacked_; }

private:
    uint8_t slotFor(Role role) const; // stock/DAF/duress -> ECC slot index

    cdc::hal::ISecureElement* se_ = nullptr;
    core::IModule::SlotRange slots_ = {};
    uint8_t gatewayPub_[64] = {};
    bool gatewaySet_ = false;
    bool hwBacked_ = true;

    // Software fallback keys (only populated if the chip cannot sign). Kept here
    // behind the same interface so the engine is identical in both modes; the
    // e-paper shows a permanent "SOFTWARE KEY" banner whenever this path is used.
    bool swFallback_ = false;
    uint8_t swPriv_[3][32] = {};  // stock, DAF, duress
    uint8_t swPub_[3][64] = {};
};

} // namespace cdc::mod_lastword
