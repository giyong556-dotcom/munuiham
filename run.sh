#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export ADMIN_PASSWORD="${ADMIN_PASSWORD:-change-me}"
export SESSION_SECRET="${SESSION_SECRET:-munuiham-dev-secret-change-in-prod}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

exec uvicorn app.main:app --host "$HOST" --port "$PORT"
