#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/web"

# Karyuk API (Vite proxies /v1 → this port)
pkill -f 'uvicorn app.main:app --host 127.0.0.1 --port 8010' 2>/dev/null || true
sleep 1
if [[ -f "$ROOT/api/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/api/.venv/bin/activate"
  set -a
  # shellcheck disable=SC2046
  export $(grep -v '^#' "$ROOT/.env" | xargs)
  set +a
  (cd "$ROOT/api" && nohup uvicorn app.main:app --host 127.0.0.1 --port 8010 >> /tmp/karyuk-cc-8010.log 2>&1 &)
  sleep 2
  if ! curl -sf -m 3 -X POST http://127.0.0.1:8010/v1/auth/dev-session >/dev/null; then
    echo "ERROR: Karyuk API did not start on 127.0.0.1:8010 (see /tmp/karyuk-cc-8010.log)"
    exit 1
  fi
fi

pkill -f "karyuk-cc/web/node_modules/.bin/vite" 2>/dev/null || true
sleep 1
cd "$ROOT/web"
nohup env -u VITE_API_BASE_URL npm run dev >> /tmp/vite-karyuk-cc.log 2>&1 &
nohup env -u VITE_API_BASE_URL npm run dev:https >> /tmp/vite-karyuk-cc-https.log 2>&1 &
sleep 2

PRIMARY_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo ""
echo "KARYUK web dev (Vite on http://0.0.0.0:5173)"
echo "  On this server:  http://127.0.0.1:5173/"
if [[ -n "${PRIMARY_IP:-}" ]]; then
  echo "  From your PC:     http://${PRIMARY_IP}:5173/"
fi
echo "  Voice (mic):  https://${PRIMARY_IP:-127.0.0.1}:5174/  — trust cert once, same paths as :5173"
echo "  SSH: ssh -L 5173:127.0.0.1:5173 -L 5174:127.0.0.1:5174 <host>"
echo "  API:  http://127.0.0.1:8010 (required for dev-session)"
echo "  Logs: tail -f /tmp/karyuk-cc-8010.log  /tmp/vite-karyuk-cc.log  /tmp/vite-karyuk-cc-https.log"
echo ""