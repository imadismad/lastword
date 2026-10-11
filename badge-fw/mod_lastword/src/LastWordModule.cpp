#include "mod_lastword/LastWordModule.h"
#include "TropicBackend.h"

#include "serial_cmd/Console.h"

namespace cdc::mod_lastword {

// One backend instance for the module's lifetime.
static TropicBackend g_backend;

LastWordModule& LastWordModule::instance() {
    static LastWordModule inst;
    return inst;
}

core::IModule::SlotRequest LastWordModule::getSlotRequest() const {
    // 3 ECC slots (stock, DAF, duress). The firmware TropicSlotMap assigns a
    // concrete, non-overlapping range (declared in the fork's tropic_slot_map.h as
    // ECC_SLOT_MOD_LASTWORD_START..END). No R-Mem needed.
    core::IModule::SlotRequest req;
    req.mapName = MODULE_NAME;
    req.minEccSlots = 3;
    req.minRmemSlots = 0;
    return req;
}

void LastWordModule::setSlotRange(const core::IModule::SlotRange& range) {
    slots_ = range;
}

bool LastWordModule::init() {
    if (!g_backend.begin(slots_)) return false;
    proto_.setBackend(&g_backend);
    state_ = core::ServiceState::INITIALIZED;
    return true;
}

bool LastWordModule::start() {
    // Generate the role keys in-chip on first boot (vierge badge), or keep the
    // existing ones. The gateway public key is installed later via PROVISION or a
    // dedicated serial command (see fork patch); until then REQUESTs are refused.
    if (!g_backend.ensureRoleKeys()) return false;
    return core::ModuleBase::start();
}

void LastWordModule::stop() {
    core::ModuleBase::stop();
}

void LastWordModule::onTick(uint32_t /*nowMs*/) {
    // No periodic work; the binary channel is driven by feedByte() from the CDC
    // RX path (wired in the fork). Left as a hook for timeouts if needed later.
}

static void cdc_sink(void* /*ctx*/, const uint8_t* bytes, size_t n) {
    // Write the framed reply straight back on the USB-CDC line.
    for (size_t i = 0; i < n; ++i) cdc::serial::Console::putchar(static_cast<char>(bytes[i]));
    cdc::serial::Console::flush();
}

void LastWordModule::feedByte(uint8_t b) {
    proto_.feedByte(b, &cdc_sink, nullptr);
}

uint8_t LastWordModule::getMenuItems(core::ModuleMenuItem* /*items*/, uint8_t /*maxItems*/) {
    return 0; // headless module: no menu entry, driven over the wire.
}

} // namespace cdc::mod_lastword

extern "C" void mod_lastword_register() {
    // Mirrors how other modules self-register with the ModuleRegistry.
    cdc::core::ModuleRegistry::instance().registerModule(
        &cdc::mod_lastword::LastWordModule::instance());
}
