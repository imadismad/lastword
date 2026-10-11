"""LoRa time-on-air (Semtech AN1200.13), to show the airtime each payment costs."""
from __future__ import annotations

import math

# Meshtastic presets: name -> (spreading factor, bandwidth Hz, coding rate denominator)
PRESETS = {
    0: ("LONG_FAST", 11, 250_000, 5),
    1: ("LONG_SLOW", 12, 125_000, 8),
    3: ("MEDIUM_SLOW", 10, 250_000, 5),
    4: ("MEDIUM_FAST", 9, 250_000, 5),
    5: ("SHORT_SLOW", 8, 250_000, 5),
    6: ("SHORT_FAST", 7, 250_000, 5),
}
MESH_OVERHEAD = 16 + 12   # Meshtastic packet header + encrypted Data protobuf framing (approx.)


def airtime_ms(app_payload: int, preset: int = 0, preamble: int = 16) -> float:
    _name, sf, bw, cr = PRESETS.get(preset, PRESETS[0])
    pl = app_payload + MESH_OVERHEAD
    t_sym = (2 ** sf) / bw * 1000.0
    de = 1 if t_sym > 16 else 0                      # low data-rate optimisation
    n = 8 + max(math.ceil((8 * pl - 4 * sf + 28 + 16) / (4 * (sf - 2 * de))) * cr, 0)
    return (preamble + 4.25) * t_sym + n * t_sym


def preset_name(preset: int) -> str:
    return PRESETS.get(preset, ("?",))[0]
