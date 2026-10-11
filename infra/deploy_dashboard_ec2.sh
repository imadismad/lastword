#!/usr/bin/env bash
# Runs ON EC2. Full dashboard-showpiece deploy against the LIVE Avalanche L1:
#   1. clone the repo + build a python venv with agent/bridge/dashboard deps
#   2. start badge-sim (--auto) under pm2
#   3. deploy a fresh LastWord + DemoUSD on the L1 with badge-sim's pubkeys
#   4. start the bridge (I4 API) pointed at the L1 + badge-sim
#   5. start the dashboard; Bedrock reader works here (EC2 can reach Bedrock)
#
# Usage: bash deploy_dashboard_ec2.sh <blockchainID> [BEDROCK_MODEL_ID]
set -uo pipefail
BC="${1:?usage: deploy_dashboard_ec2.sh <blockchainID> [bedrock_model]}"
BEDROCK_MODEL="${2:-}"
RPC="http://127.0.0.1:9650/ext/bc/${BC}/rpc"
REPO=/home/ubuntu/lastword
FORGE="$HOME/.foundry/bin/forge"
export PATH="$HOME/.foundry/bin:$PATH"

# anvil-style well-known demo accounts (same as local): deployer0, agent1, bridge2
DEPLOYER_PK=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
AGENT_ADDR=0x70997970C51812dc3A010C7d01b50e0d17dc79C8
AGENT_PK=0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d
BRIDGE_ADDR=0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC
BRIDGE_PK=0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a
SUPPLIER=0x1111111111111111111111111111111111111111

echo "=== 0. system deps (venv + pip) ==="
sudo apt-get update -y >/dev/null 2>&1
sudo apt-get install -y python3.12-venv python3-pip >/dev/null 2>&1 || true

echo "=== 1. repo ==="
# Source is delivered as a tarball extracted to $REPO (repo is private; no clone).
if [ ! -f "$REPO/dashboard/server.py" ]; then
  echo "ERROR: source not found at $REPO (expected it to be delivered by scp+tar)"; exit 1
fi
cd "$REPO"

echo "=== 2. venv + deps ==="
if [ ! -x "$REPO/.venv/bin/python" ]; then
  python3 -m venv "$REPO/.venv"
fi
PY="$REPO/.venv/bin/python"
"$PY" -m pip install -q --upgrade pip >/dev/null 2>&1
"$PY" -m pip install -q \
  web3 pyserial python-dotenv cryptography fastapi uvicorn python-multipart \
  jsonschema pypdf requests boto3 eth-account >/dev/null 2>&1
# install the local libs editable so imports resolve
"$PY" -m pip install -q -e ./proto -e ./agent 2>/dev/null || true

echo "=== 3. badge-sim under pm2 ==="
pm2 delete lw-badge >/dev/null 2>&1 || true
pm2 start "$PY" --name lw-badge -- "$REPO/badge-sim/badge_sim.py" --tcp 127.0.0.1:8766 --auto
sleep 3

echo "=== 4. deploy fresh contract on the L1 (badge-sim pubkeys) ==="
# read the three pubkeys from badge-sim
PUB=$("$PY" "$REPO/badge-sim/badge_sim.py" --print-pubkeys)
STOCK=$(echo "$PUB" | "$PY" -c "import sys,json; print(json.load(sys.stdin)['stock'])")
DAF=$(echo "$PUB"   | "$PY" -c "import sys,json; print(json.load(sys.stdin)['daf'])")
DUR=$(echo "$PUB"   | "$PY" -c "import sys,json; print(json.load(sys.stdin)['duress'])")

export PRIVATE_KEY=$DEPLOYER_PK
export AGENT_ADDR BRIDGE_ADDR
export COADMIN_ADDR=0x90F79bf6EB2c4f870365E785982E1f101E93b906
export GUARDIAN_ADDR=0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65
export DAF_QX=0x${DAF:0:64}   DAF_QY=0x${DAF:64}
export STOCK_QX=0x${STOCK:0:64} STOCK_QY=0x${STOCK:64}
export DURESS_QX=0x${DUR:0:64}  DURESS_QY=0x${DUR:64}
export SUPPLIER_ADDR=$SUPPLIER SUPPLIER_CAP=1000000000
export WHITELIST_DELAY=0 PARALLEL_CAP=50000000

cd "$REPO/contracts"
# forge libs are gitignored, so install them on a fresh clone (idempotent).
if [ ! -d lib/forge-std ]; then
  "$FORGE" install foundry-rs/forge-std --no-git >/tmp/lib1.log 2>&1 || \
    git clone --depth 1 https://github.com/foundry-rs/forge-std lib/forge-std >/tmp/lib1.log 2>&1
fi
if [ ! -d lib/openzeppelin-contracts ]; then
  "$FORGE" install OpenZeppelin/openzeppelin-contracts@v5.7.0 --no-git >/tmp/lib2.log 2>&1 || \
    git clone --depth 1 -b v5.7.0 https://github.com/OpenZeppelin/openzeppelin-contracts lib/openzeppelin-contracts >/tmp/lib2.log 2>&1
fi
"$FORGE" script script/Deploy.s.sol --rpc-url "$RPC" --broadcast --skip-simulation >/tmp/deploy.log 2>&1 \
  || { echo "deploy FAILED"; tail -30 /tmp/deploy.log; exit 1; }
LW=$("$PY" - "$REPO/contracts/broadcast/Deploy.s.sol" <<'PYEOF'
import json,os,sys
root=sys.argv[1]; newest=None
for r,_,fs in os.walk(root):
    for f in fs:
        if f=="run-latest.json":
            p=os.path.join(r,f)
            if newest is None or os.path.getmtime(p)>os.path.getmtime(newest): newest=p
d=json.load(open(newest))
for tx in d.get("transactions",[]):
    if tx.get("contractName")=="LastWord":
        print(tx["contractAddress"]); break   # first match only
PYEOF
)
echo "LastWord=$LW"
cd "$REPO"

echo "=== 5. bridge under pm2 ==="
pm2 delete lw-bridge >/dev/null 2>&1 || true
LASTWORD_RPC_URL="$RPC" LASTWORD_CONTRACT_ADDRESS="$LW" \
  BRIDGE_PRIVATE_KEY="$BRIDGE_PK" AGENT_PRIVATE_KEY="$AGENT_PK" \
  BRIDGE_TRANSPORT="tcp:127.0.0.1:8766" BRIDGE_HOST=127.0.0.1 BRIDGE_PORT=8099 \
  PYTHONPATH="$REPO/bridge/src:$REPO/proto/src" \
  pm2 start "$PY" --name lw-bridge -- -m lastword_bridge.main
sleep 5

echo "=== 6. dashboard under pm2 ==="
pm2 delete lw-dashboard >/dev/null 2>&1 || true
BEDROCK_MODEL_ID="$BEDROCK_MODEL" AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}" \
  BRIDGE_URL="http://127.0.0.1:8099" DASH_EXPLORER_URL="http://127.0.0.1:3000" \
  DASH_WHITELIST_FILE="$REPO/agent/demo/whitelist.json" \
  PYTHONPATH="$REPO/proto/src:$REPO/agent/src" \
  pm2 start "$PY" --name lw-dashboard -- -m uvicorn dashboard.server:app --host 127.0.0.1 --port 8090
pm2 save >/dev/null 2>&1 || true
sleep 4

echo "=== 7. checks ==="
curl -s -m 8 http://127.0.0.1:8099/health; echo
curl -s -m 8 -o /dev/null -w 'dashboard_http=%{http_code}\n' http://127.0.0.1:8090/api/config
pm2 list | grep -E 'lw-|name'
echo "LW_ADDR=$LW"
echo "ALL_DONE"
