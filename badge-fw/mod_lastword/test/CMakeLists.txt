# Host-side parity test for mod_lastword. Builds WITHOUT ESP-IDF: just a host C++
# compiler + system mbedTLS. Proves the C++ badge engine matches proto/vectors.json
# byte-for-byte before anything is flashed.
#
# Usage:
#   cmake -S badge-fw/mod_lastword/test -B build/badge-parity
#   cmake --build build/badge-parity
#   ./build/badge-parity/parity_test            # run from repo root (finds proto/vectors.json)
#
# Needs: libmbedtls / libmbedcrypto dev headers (Debian/Ubuntu: libmbedtls-dev).

cmake_minimum_required(VERSION 3.16)
project(mod_lastword_parity CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(MOD ${CMAKE_CURRENT_SOURCE_DIR}/..)

add_executable(parity_test
    parity_test.cpp
    ${MOD}/src/wire.cpp
    ${MOD}/src/BadgeProtocol.cpp
    ${MOD}/src/crypto_mbedtls.cpp
)
target_include_directories(parity_test PRIVATE ${MOD}/include ${MOD}/src)

# Link mbedTLS (3.x splits into mbedcrypto/mbedx509/mbedtls).
find_library(MBEDCRYPTO mbedcrypto)
find_library(MBEDTLS mbedtls)
find_library(MBEDX509 mbedx509)
target_link_libraries(parity_test PRIVATE
    ${MBEDTLS} ${MBEDX509} ${MBEDCRYPTO})

if(NOT MBEDCRYPTO)
    message(WARNING "libmbedcrypto not found. Install libmbedtls-dev (Debian/Ubuntu) "
                    "or point CMAKE_PREFIX_PATH at your mbedTLS install.")
endif()
