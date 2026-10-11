#!/usr/bin/env bash
# Apply (or re-check) the LASTWORD fork patch inside the cdc-badge-os submodule.
#
# The patch wires mod_lastword into the firmware build without modifying files
# tracked by the submodule's own history permanently — it is applied to the
# submodule working tree just before building. Re-running is safe: it checks
# first and skips if already applied.
#
# Usage:
#   badge-fw/patches/apply.sh          # apply the patch
#   badge-fw/patches/apply.sh --revert # revert it (git checkout the 4 files)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUB="$HERE/../cdc-badge-os"
PATCH="$HERE/lastword.patch"

if [ ! -d "$SUB/.git" ] && [ ! -f "$SUB/.git" ]; then
    echo "error: submodule not initialized. Run:"
    echo "  git submodule update --init --recursive badge-fw/cdc-badge-os"
    exit 1
fi

if [ "${1:-}" = "--revert" ]; then
    git -C "$SUB" checkout -- CMakeLists.txt main/CMakeLists.txt \
        main/module_defaults.h main/tropic_slot_map.h
    echo "reverted."
    exit 0
fi

# Already applied? (patch applies cleanly in reverse -> it's in place)
if git -C "$SUB" apply --reverse --check "$PATCH" >/dev/null 2>&1; then
    echo "already applied — nothing to do."
    exit 0
fi

git -C "$SUB" apply --check "$PATCH"
git -C "$SUB" apply "$PATCH"
echo "applied: 4 files (CMakeLists.txt, main/CMakeLists.txt, module_defaults.h, tropic_slot_map.h)"
