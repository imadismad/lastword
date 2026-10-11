"""Find the demo hardware by USB identity (COM numbers change on every replug)."""
from __future__ import annotations

import os

# CH34x USB-UART on the LILYGO T3 LoRa32 nuggets
NUGGET_VID = 0x1A86
GATEWAY_SERIAL = os.environ.get("LW_GATEWAY_NUGGET_SERIAL", "5A5B009671")   # nugget-1
STATION_SERIAL = os.environ.get("LW_STATION_NUGGET_SERIAL", "5A5B009843")   # nugget-3
# CDC badge (cdc-badge-os enumerates with this VID/PID; override with LW_BADGE_PORT)
BADGE_VID, BADGE_PID = 0x08E6, 0x4433


def _ports():
    from serial.tools import list_ports
    return list(list_ports.comports())


def find_port(serial_number: str) -> str:
    for p in _ports():
        if p.vid == NUGGET_VID and (p.serial_number or "").upper() == serial_number.upper():
            return p.device
    return ""


def gateway_port() -> str:
    return os.environ.get("LW_GATEWAY_PORT") or find_port(GATEWAY_SERIAL)


def station_port() -> str:
    return os.environ.get("LW_STATION_PORT") or find_port(STATION_SERIAL)


def badge_port() -> str:
    if os.environ.get("LW_BADGE_PORT"):
        return os.environ["LW_BADGE_PORT"]
    for p in _ports():
        if p.vid == BADGE_VID and p.pid == BADGE_PID:
            return p.device
    return ""


def inventory() -> dict:
    return {"gateway": gateway_port(), "station": station_port(), "badge": badge_port()}
