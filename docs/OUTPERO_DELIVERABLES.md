# Outpero integration — final deliverables

## 1. Integration architecture

```
Dashboard (/app/voice-agents)
  → Karyuk API (/v1/workspaces/{id}/outpero/*)
  → Outpero Lead Intake API (api.outpero.com)
  → Voice agent call
  → Outpero post-call webhook call.ended
  → Karyuk /v1/webhooks/outpero/{workspace_id}
  → HMAC verify + idempotent event store
  → Upsert Call (provider=outpero) + Lead (lead_source=outpero)
  → Existing Leads + Conversations UI
```

## 2. Outpero API endpoints used

- `POST /lead-intake/{slug}`
- `GET /lead-intake/{slug}/schema`
- `GET /lead-intake/{slug}/calls/{call_id}`
- Incoming post-call webhook `call.ended` (HMAC `X-Outpero-Signature`)

## 3. Supported / unsupported

See `OUTPERO_INTEGRATION.md`. Summary: intake + schema + call status + webhooks are supported; remote agent CRUD/list, browser voice test, and webhook retries are not.

## 4. Backend files created or modified

**Created**

- `api/app/services/outpero/__init__.py`
- `api/app/services/outpero/client.py`
- `api/app/services/outpero/signatures.py`
- `api/app/services/outpero/sync.py`
- `api/app/services/outpero/agents.py`
- `api/app/models/outpero.py`
- `api/app/routers/outpero.py`
- `api/alembic/versions/20260320_0006_outpero_integration.py`
- `api/tests/test_outpero_signatures.py`
- `api/tests/test_outpero_sync.py`
- `api/tests/test_outpero_webhook_http.py`
- `docs/OUTPERO_INTEGRATION.md`
- `docs/OUTPERO_DELIVERABLES.md`

**Modified**

- `api/app/config.py`
- `api/app/main.py`
- `api/app/models/__init__.py`
- `api/app/models/platform.py` (Lead + Call extensions)
- `api/app/routers/platform.py` (richer lead/call payloads)
- `.env` (Outpero vars)

## 5. Frontend files created or modified

**Created**

- `web/src/pages/app/VoiceAgentsPage.tsx`

**Modified**

- `web/src/App.tsx` (route `/app/voice-agents`)
- `web/src/components/app/AppSidebar.tsx`
- `web/src/pages/app/CallDetailPage.tsx`
- `web/src/pages/app/ConversationsPage.tsx`
- `web/src/pages/app/LeadsPage.tsx`

## 6. Database migrations

- `20260320_0006_outpero_integration` — applied successfully against Postgres

## 7. Environment variables

```
OUTPERO_API_BASE_URL=https://api.outpero.com
OUTPERO_WEBHOOK_MAX_AGE_SECONDS=300
OUTPERO_WEBHOOK_SHARED_SECRET=
PUBLIC_API_BASE_URL=https://karyuk.wayfinderops.com
```

Per-agent: slug, lead secret, webhook signing secret (stored in DB, never sent to browser in full).

## 8–11. Connect / test / verify

Documented in `OUTPERO_INTEGRATION.md`.

## 12. Test results

```
tests.test_outpero_signatures — 4 passed
tests.test_outpero_sync — 6 passed (incl. idempotent lead/call upsert)
tests.test_outpero_webhook_http — 2 passed (401 bad sig, 200 valid → lead+call)
```

## Remaining limitations

1. **No Outpero credentials in this environment** — live intake/call against api.outpero.com requires your employee slug + secrets.
2. Outpero does **not** retry webhooks; Karyuk returns 200 quickly and supports `POST .../calls/{id}/refresh` reconciliation.
3. Unanswered/never-connected dials produce **no** `call.ended` webhook (Outpero limitation).
4. Agent list/settings must be registered locally; Outpero has no public agent management API.
5. Recording URLs expire after ~24h per Outpero docs — download promptly if long-term retention is required.
6. Restart the running API process after deploy so new routes are loaded.
