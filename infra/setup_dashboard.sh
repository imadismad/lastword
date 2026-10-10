#!/usr/bin/env bash
# Runs ON EC2. Starts the LASTWORD agent dashboard (FR-16) under pm2, next to the
# bridge + explorer. Bedrock is reachable from EC2, so the Bedrock reader works here.
#
# Prereqs on the box: the repo at /home/ubuntu/lastword (or $REPO), a python venv with
# the agent+bridge+dashboard deps, and the bridge already serving the I4 API.
#
# Usage: bash setup_dashboard.sh [BRIDGE_URL] [EXPLORER_URL]
set -uo pipefail
REPO="${REPO:-/home/ubuntu/lastword}"
BRIDGE_URL="${1:-http://127.0.0.1:8099}"
EXPLORER_URL="${2:-http://127.0.0.1:3000}"
PORT="${DASH_PORT:-8090}"
VENV="${VENV:-$REPO/.venv}"
PY="$VENV/bin/python"

cd "$REPO" || { echo "repo not found at $REPO"; exit 1; }

echo "=== deps ==="
"$PY" -m pip install -q fastapi uvicorn python-multipart jsonschema pypdf boto3 requests \
  web3 pyserial python-dotenv 2>/dev/null || true

echo "=== pm2 dashboard on :$PORT ==="
command -v pm2 >/dev/null 2>&1 || sudo npm install -g pm2 >/dev/null 2>&1 || true
pm2 delete lw-dashboard >/dev/null 2>&1 || true

# Bedrock env is inherited from the shell/pm2 environment if present:
#   BEDROCK_MODEL_ID, BEDROCK_GUARDRAIL_ID, AWS_DEFAULT_REGION, AWS_* creds
BRIDGE_URL="$BRIDGE_URL" DASH_EXPLORER_URL="$EXPLORER_URL" \
  pm2 start "$PY" --name lw-dashboard -- \
  -m uvicorn dashboard.server:app --host 127.0.0.1 --port "$PORT"

pm2 save >/dev/null 2>&1 || true
sleep 3
echo "=== check ==="
curl -s -m 8 -o /dev/null -w 'dashboard_http=%{http_code}\n' "http://127.0.0.1:$PORT/api/config"
pm2 list | grep -E 'lw-dashboard|name' || true
echo "ALL_DONE  (tunnel with: ssh -L $PORT:127.0.0.1:$PORT ...)"
