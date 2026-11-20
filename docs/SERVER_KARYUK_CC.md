# Karyuk on Hetzner (`karyuk-cc`)

This desktop repo deploys to the **karyuk** server (SSH host `karyuk`, `2.31.134.192`) in **`/root/karyuk-cc`**.

The older monolith lives in `/root/karyuk` with Caddy at `karyuk.wayfinderops.com` — keep that separate; **karyuk-cc** is this FastAPI + Vite + Postgres stack.

## From your PC

```powershell
# Sync code (no secrets)
.\scripts\deploy-karyuk-cc.ps1

# Include local .env (careful: contains API keys)
.\scripts\deploy-karyuk-cc.ps1 -IncludeEnv

# Copy secrets only
scp .env karyuk:/root/karyuk-cc/.env
```

SSH: `ssh karyuk`

## On the server (first setup)

```bash
cd /root/karyuk-cc
docker compose up -d db

cd api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head

# Edit .env: DATABASE_URL, PUBLIC_API_BASE_URL, Exotel, Sarvam keys
nano ../.env
```

Run API (example):

```bash
cd /root/karyuk-cc/api
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8010
```

## Web UI (Vite)

```bash
./scripts/start-web-dev.sh
# or: cd web && npm run dev
```

**`http://localhost:5173` on your laptop is not this server** unless you forward the port.

| Where you open the browser | URL |
|----------------------------|-----|
| On the server | `http://127.0.0.1:5173/` |
| On your PC (no tunnel) | **`https://2.31.134.192:5173/`** (accept self-signed cert once — required for browser mic) |
| On your PC with SSH tunnel | `ssh -L 5173:127.0.0.1:5173 karyuk` then **`https://localhost:5173/`** |
| Cursor **Ports** | Forward **5173** to the remote host, then use the forwarded localhost link |

Vite proxies `/v1` and `/health` to `127.0.0.1:8010`, so the API must be running on 8010 for voice preview and workspace API calls.

On this server, Caddy on `karyuk.wayfinderops.com` proxies `/v1/*` and `/health` to `127.0.0.1:8010` (snippet in `infra/caddy-karyuk-cc.snippet`; live file `/root/karyuk/infra/Caddyfile`).

## Exotel + Sarvam on server

- `PUBLIC_API_BASE_URL=https://karyuk.wayfinderops.com`
- Voicebot URL: `https://<host>/v1/webhooks/exotel/voicebot`
- `INBOUND_VOICE_MODE=sarvam` when `SARVAM_API_KEY` is set

### End-to-end connectivity check

```bash
cd /root/karyuk-cc
./scripts/check-inbound-e2e.sh        # DB, health, voicebot, public WSS
./scripts/check-inbound-e2e.sh --sarvam # also pings Sarvam TTS quota
```

See `docs/EXOTEL_INBOUND_FLOW.md` — **Voicebot** applet for Sarvam media; `/v1/webhooks/exotel/inbound` is XML Gather only.