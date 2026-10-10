#!/usr/bin/env bash
# Runs ON EC2. Deploys the EROL/CodeNekt block explorer against the LASTWORD L1.
#   - MongoDB in Docker
#   - backend API (:3002) + indexer  (ethers -> L1 RPC)
#   - frontend SvelteKit (:3000)  -> backend API + L1 RPC
# Idempotent-ish. Reads the L1 RPC path from arg $1.
set -uo pipefail
RPC_PATH="${1:?usage: setup_explorer.sh <blockchainID>}"
RPC_URL="http://127.0.0.1:9650/ext/bc/${RPC_PATH}/rpc"
# For the browser (frontend), the Dell reaches the RPC via its own tunnel on localhost:9650
PUBLIC_RPC_URL="http://127.0.0.1:9650/ext/bc/${RPC_PATH}/rpc"

echo "=== Node.js ==="
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - >/dev/null 2>&1
  sudo apt-get install -y nodejs >/dev/null 2>&1
fi
node --version

echo "=== MongoDB (Docker) ==="
if ! sudo docker ps --format '{{.Names}}' | grep -q lastword-mongo; then
  sudo docker rm -f lastword-mongo >/dev/null 2>&1 || true
  sudo docker run -d --name lastword-mongo -p 127.0.0.1:27017:27017 \
    --restart unless-stopped mongo:7 >/dev/null
  sleep 5
fi
sudo docker ps --filter name=lastword-mongo --format '{{.Names}} {{.Status}}'

cd /home/ubuntu/explorer || { echo "explorer dir missing"; exit 1; }

echo "=== backend ==="
cat > backend/.env <<EOF
PORT=3002
DB_STRING=mongodb://127.0.0.1:27017
DB_NAME=lastword_explorer
RPC_URL=${RPC_URL}
DISABLE_SIGNATURE_LOOKUP=1
EOF

# Apply the LASTWORD overlay (see infra/explorer-patches/README.md).
# These make the backend index transactions (not just blocks) and avoid the
# unreachable OpenChain signature lookup. Patches are copied here by the Dell
# before this script runs; fall back to a no-op if absent.
PATCH_DIR="/home/ubuntu/explorer-patches"
if [ -d "$PATCH_DIR/backend" ]; then
  echo "applying explorer patches from $PATCH_DIR"
  cp -f "$PATCH_DIR/backend/src/services/BlockService.ts"       backend/src/services/BlockService.ts
  cp -f "$PATCH_DIR/backend/src/services/TransactionService.ts" backend/src/services/TransactionService.ts
  cp -f "$PATCH_DIR/backend/backfill.ts"                        backend/backfill.ts
else
  echo "WARN: $PATCH_DIR not found - running stock backend (transactions may not index)"
fi

cd backend
npm install >/tmp/be_install.log 2>&1 || { echo "backend npm install FAILED"; tail -20 /tmp/be_install.log; }
# start API + indexer under pm2 (install pm2 if needed)
sudo npm install -g pm2 >/dev/null 2>&1 || true
pm2 delete lw-api lw-indexer >/dev/null 2>&1 || true
pm2 start "npm run start:api" --name lw-api
DISABLE_SIGNATURE_LOOKUP=1 pm2 start "npm run start:indexer" --name lw-indexer --update-env
# Backfill history so pre-existing LASTWORD txs appear (indexer only sees new blocks).
echo "=== backfill ==="
DISABLE_SIGNATURE_LOOKUP=1 npx ts-node backfill.ts 2>&1 | tail -5 || echo "backfill failed (non-fatal)"
cd ..

echo "=== frontend ==="
cat > frontend/.env <<EOF
PUBLIC_RPC_URL=${PUBLIC_RPC_URL}
PUBLIC_GAS_UNIT=Gwei
PUBLIC_NATIVE_SYMBOL=LWT
PUBLIC_SOURCIFY_VERIFY_URL=
EXPLORER_API_URL=http://127.0.0.1:3002
DB_STRING=mongodb://127.0.0.1:27017
DB_NAME=lastword_explorer
NATIVE_SYMBOL=LWT
EOF
cd frontend
npm install >/tmp/fe_install.log 2>&1 || { echo "frontend npm install FAILED"; tail -20 /tmp/fe_install.log; }
npm run build >/tmp/fe_build.log 2>&1 || { echo "frontend build FAILED"; tail -30 /tmp/fe_build.log; }
# SvelteKit default (node adapter) -> run preview or the built node server on :3000
pm2 delete lw-frontend >/dev/null 2>&1 || true
PORT=3000 pm2 start "npm run preview -- --host 127.0.0.1 --port 3000" --name lw-frontend
cd ..

pm2 save >/dev/null 2>&1 || true
echo "=== PM2 STATUS ==="
pm2 list
echo "ALL_DONE"
