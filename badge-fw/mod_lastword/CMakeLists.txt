# mod_lastword — LASTWORD payment-approval module for cdc-badge-os.
#
# This component is kept OUTSIDE the cdc-badge-os submodule so upstream stays
# clean. To build it into the firmware, the fork adds this directory to
# EXTRA_COMPONENT_DIRS and lists "mod_lastword" in main/CMakeLists.txt MODULES
# (see badge-fw/README.md "Wiring mod_lastword into cdc-badge-os").

idf_component_register(
    SRCS
        "src/LastWordModule.cpp"
        "src/BadgeProtocol.cpp"
        "src/TropicBackend.cpp"
        "src/wire.cpp"
        "src/crypto_mbedtls.cpp"
    INCLUDE_DIRS
        "include"
    PRIV_INCLUDE_DIRS
        "src"
    REQUIRES
        cdc_core
        cdc_hal
        cdc_os_ui
        serial_cmd
        cdc_log
        mbedtls
        freertos
)
