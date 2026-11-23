# Outpero Phase-1 inbound → Calls (staging)

**Status:** Staging endpoint live. **Phase 1 real-call QA: pending** (Send test HTTP 200 is not evidence). Not production-enabled. Not `MODULE_COMPLETE`.

## Public webhook URL (paste in Outpero)

```
https://karyuk.wayfinderops.com/v1/webhooks/outpero/inbound/harish-staging
```

- Trigger: `call.ended` (post-call)
- Method: `POST`
- Signing: HMAC-SHA256 over `{timestamp}.{raw_body}`
- Headers: `X-Outpero-Timestamp`, `X-Outpero-Signature` (`sha256=…`)
- Workspace is **not** in the URL. Binding is server-side via `connection_key=harish-staging`.

## Outpero dashboard steps

1. Open the Harish AI employee (`slug` `2p5dFQKubqRMsuYMOdzPTg`).
2. **Post-Call → Webhooks** → add the URL above.
3. Enable signing. Karyuk must use the **Outpero-generated** signing secret (server `OUTPERO_INBOUND_WEBHOOK_SECRET` + `harish-staging` connection). Do not invent a second secret.
4. Save. Use **Test Send**, or place one real inbound call to the bound DID.
5. Confirm a new row appears under Karyuk **Calls** for workspace `b96e99eb-2bda-4bdd-9aa9-ba9bc43762e3`.

**Note:** Outpero **Test Send** currently posts JSON **without** `X-Outpero-Timestamp` / `X-Outpero-Signature` (confirmed 2026-11-21: `test-e51f1a8c` → HTTP 200). Staging accepts that only when `OUTPERO_INBOUND_ACCEPT_UNSIGNED=true`. Signed real `call.ended` deliveries still verify HMAC when those headers are present. Prior 401s were from rejecting unsigned Test Send before that staging flag.

## Phase-1 allowlist (what we keep)

| Kept | Not kept / not acted on |
|------|-------------------------|
| `call_id`, status, direction, employee/slug | transcript |
| from/to (DID), duration, started/ended | recording URL |
| hangup_reason | summary |
| | captured / leads / booking complete |

## Binding (server-side)

| Field | Value |
|-------|--------|
| `connection_key` | `harish-staging` |
| Workspace | `b96e99eb-2bda-4bdd-9aa9-ba9bc43762e3` |
| Employee slug | `2p5dFQKubqRMsuYMOdzPTg` |
| DID (`OUTPERO_INBOUND_DID_E164`) | `+919000017599` (bound on `harish-staging`) — operator must confirm this is the live answered inbound number |
| Feature flag | `OUTPERO_INBOUND_IMPORT_ENABLED=true` |
| Production | Hard-off when `KARYUK_DEPLOYMENT` / `APP_ENV` is `production`/`prod` |

## Proven locally (2026-03-21)

- `POST` signed body → public HTTPS **200** `{accepted:true}`
- Unsigned → **401**
- Call row created with `provider=outpero`; transcript/summary/recording **null**; sensitive payload keys excluded from `captured_fields`
- Migration `20261121_0010` applied; connection bootstrapped on API startup
- Unit tests: `tests.test_outpero_inbound_phase1` + `tests.test_outpero_signatures` **OK**

## Reconcile / recovery

- Durable event key: `inbound:harish-staging:{call_id}` (unique per workspace)
- Duplicate deliveries return `200` with `duplicate: true` after processed
- Failed processing leaves event `failed`; a later delivery can re-queue background processing
- Legacy workspace-id webhook (`/v1/webhooks/outpero/{workspace_id}`) is unchanged and separate

## Explicit non-goals (this phase)

- No Harish script / routing / Lead Intake / LiveKit / M02 changes
- No production enable
- No localhost or guessed URL for Outpero
- No claim of MODULE_COMPLETE until real-call QA + human acceptance
