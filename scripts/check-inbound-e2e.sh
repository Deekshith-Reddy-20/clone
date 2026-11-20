#!/usr/bin/env bash
# End-to-end inbound connectivity (DB, API, Caddy, Voicebot, optional Vite + Sarvam).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a
export KARYUK_VOICE_BUILD_SHA="${KARYUK_VOICE_BUILD_SHA:-$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo local)}"

if ! curl -sf "http://127.0.0.1:8010/health" >/dev/null; then
  echo "Starting API on 127.0.0.1:8010..."
  cd "$ROOT/api"
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pkill -f "uvicorn app.main:app --host 127.0.0.1 --port 8010" 2>/dev/null || true
  sleep 1
  nohup uvicorn app.main:app --host 127.0.0.1 --port 8010 >> /tmp/karyuk-cc-8010.log 2>&1 &
  sleep 2
fi

cd "$ROOT/api"
# shellcheck disable=SC1091
source .venv/bin/activate
exec python scripts/e2e_inbound_connect.py --ws "$@"