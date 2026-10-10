#pragma once

// mod_lastword — LASTWORD payment-approval module for cdc-badge-os.
//
// Role in the system (see cahier des charges s8, s16bis, and proto/SPEC.md I1-I3):
//   The badge is the ONLY authority that can approve a payment. This module makes
//   the real CDC badge behave exactly like badge-sim/badge_sim.py, byte-for-byte on
//   the wire, so the bridge/contract accept its signatures with no change:
//     1. receive an I3 message (COBS + CRC-16) over the USB-CDC binary channel,
//     2. on REQUEST: decrypt the I2 frame (AES-256-GCM, per-message HKDF key),
//     3. recompute the SHA-256 digest from the DECODED intent fields (never trust
//        free text from the agent),
//     4. verify the gateway P-256 signature over that digest BEFORE displaying,
//     5. show the role banner + economic fields on the e-paper,
//     6. ask for the role PIN on the keypad,
//     7. sign the digest with the role's P-256 key in the TROPIC01 (hardware),
//        or a software key fallback (banner shown) if HW signing is unavailable,
//     8. return the I2 response frame.
//
// What this module must NEVER do (hard rules from the cahier des charges s16ter / s17):
//   - never write the TROPIC01 I-Config (irreversible),
//   - never touch / invalidate a pairing-key slot (ISecureElement marks these
//     DANGEROUS, IRREVERSIBLE),
//   - never update the TROPIC01 firmware.
// It only generates P-256 keys in its OWN assigned ECC slots, reads their public
// keys, and asks the chip to sign a 32-byte digest.
//
// Slot allocation: this module declares a SlotRequest (3 ECC slots: stock, DAF,
// duress). The firmware's TropicSlotMap assigns a non-overlapping range at build;
// we do NOT hardcode slots 0/8/16 (those collide with attestation/PIV/FIDO2 in the
// stock tropic_slot_map.h — see getSlotRequest()).

#include "cdc_core/ModuleBase.h"
#include "mod_lastword/BadgeProtocol.h"

#include <cstdint>

namespace cdc::mod_lastword {

/// Fixed module identity. The MODULE_ID must be unique in tropic_slot_map.h and
/// is never reused (see the fork patch notes in badge-fw/README.md).
inline constexpr const char* MODULE_NAME = "mod_lastword";

class LastWordModule : public core::ModuleBase {
public:
    bool init() override;
    bool start() override;
    void stop() override;
    void onTick(uint32_t nowMs) override;

    const char* getVersion() const override { return "0.1"; }

    // Three P-256 ECC slots (stock, DAF, duress), generated in-chip at provisioning.
    core::IModule::SlotRequest getSlotRequest() const override;
    void setSlotRange(const core::IModule::SlotRange& range) override;

    uint8_t getMenuItems(core::ModuleMenuItem* items, uint8_t maxItems) override;

    static LastWordModule& instance();

    // --- Binary I3 channel ---------------------------------------------------
    // The USB-CDC SerialCmd processor is a line/text dispatcher; LASTWORD frames
    // are binary COBS. The fork wires the raw CDC RX bytes to feedByte() when the
    // module is active (see badge-fw/README.md "Wiring the binary channel"). Each
    // completed COBS frame (terminated by 0x00) is handed to the protocol engine
    // and the response is written straight back to the CDC TX.
    void feedByte(uint8_t b);

private:
    LastWordModule() : ModuleBase(MODULE_NAME) {}

    // The protocol engine is transport-agnostic and hardware-agnostic; it calls
    // back into this module for signing (TROPIC01 or software fallback), display
    // and PIN entry. Keeping it separate lets us unit-test it off-device against
    // proto/vectors.json (see badge-fw/mod_lastword/test).
    BadgeProtocol proto_;

    core::IModule::SlotRange slots_ = {};
    bool provisioned_ = false;
};

} // namespace cdc::mod_lastword

extern "C" void mod_lastword_register();
