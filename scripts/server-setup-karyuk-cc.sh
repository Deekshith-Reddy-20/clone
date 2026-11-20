#!/usr/bin/env bash
# First-time setup on Hetzner /root/karyuk-cc
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Missing .env — copy from your PC: scp .env karyuk:/root/karyuk-cc/.env"
  exit 1
fi

docker compose up -d db

cd api
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
alembic upgrade head

echo "OK. Start API: cd $ROOT/api && source .venv/bin/activate && uvicorn app.main:app --host 127.0.0.1 --port 8010"