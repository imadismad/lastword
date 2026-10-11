#include "mod_lastword/LastWordModule.h"
#include "TropicBackend.h"

#include "serial_cmd/Console.h"
#include "serial_cmd/ICommandRegistry.h"
#include "cdc_core/ModuleRegistry.h"

#include "esp_timer.h"

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

    // Register the console command that flips the serial line into binary mode.
    cdc::serial::Command cmd{};
    cmd.name = "lastword-bin";
    cmd.help = "Enter LASTWORD binary (I3) mode on this serial line";
    cmd.handler = &cmd_lastword_bin;
    cmd.moduleName = MODULE_NAME;
    cmd.requiresAuth = false;
    cdc::serial::getCommandRegistry().registerCommand(cmd);

    return core::ModuleBase::start();
}

void LastWordModule::stop() {
    // Make sure we are not holding the serial line if the module is stopped.
    cdc::serial::getCommandRegistry().setByteInterceptor(nullptr);
    cdc::serial::getCommandRegistry().unregisterModule(MODULE_NAME);
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

// --- binary channel via the command-registry ByteInterceptor -----------------
// Entering: the host sends the text command "lastword-bin". Its handler installs
// a byte interceptor; from then on every serial byte goes to onInterceptedByte()
// until an idle timeout removes the interceptor (so a half-sent frame can never
// wedge the console). This is the firmware's own raw-stream mechanism; no main.cpp
// change is needed.
static uint64_t s_lastRxUs = 0;
static constexpr uint64_t BINARY_IDLE_TIMEOUT_US = 3'000'000; // 3 s

static void onInterceptedByte(uint8_t b) {
    uint64_t now = static_cast<uint64_t>(esp_timer_get_time());
    // Idle timeout: drop back to the text console if the stream stalled.
    if (s_lastRxUs != 0 && (now - s_lastRxUs) > BINARY_IDLE_TIMEOUT_US) {
        cdc::serial::getCommandRegistry().setByteInterceptor(nullptr);
        s_lastRxUs = 0;
        return;
    }
    s_lastRxUs = now;
    LastWordModule::instance().feedByte(b);
}

static void cmd_lastword_bin(const char* /*args*/) {
    // Switch the serial line into raw binary mode for LASTWORD I3 frames.
    s_lastRxUs = static_cast<uint64_t>(esp_timer_get_time());
    cdc::serial::getCommandRegistry().setByteInterceptor(&onInterceptedByte);
    // No prompt/echo after this point; the host now speaks binary.
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
