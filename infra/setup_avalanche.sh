#!/usr/bin/env bash
# Runs ON the EC2 node. Fully non-interactive create + local deploy of the LASTWORD L1.
set -uo pipefail
export PATH="$PATH:/home/ubuntu/bin"

BC="lastword"
GENESIS="/home/ubuntu/genesis.json"
# anvil account 0 (deployer) is the validator-manager owner / prefunded in genesis
VM_OWNER="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"

echo "=== avalanche version ==="
avalanche --version

echo "=== (re)create $BC (non-interactive, non-sovereign subnet, from genesis) ==="
avalanche blockchain create "$BC" \
  --evm \
  --genesis "$GENESIS" \
  --evm-token LWT \
  --sovereign=false \
  --icm=false \
  --latest \
  --force --skip-update-check 2>&1 | tail -40
echo "create_rc=${PIPESTATUS[0]}"

echo "=== deploy $BC locally (ewoq funded key, non-interactive) ==="
avalanche blockchain deploy "$BC" --local --ewoq --skip-update-check 2>&1 | tail -80
echo "deploy_rc=${PIPESTATUS[0]}"

echo "=== describe (RPC + chain id) ==="
avalanche blockchain describe "$BC" 2>&1 | tail -80
echo "ALL_DONE"
