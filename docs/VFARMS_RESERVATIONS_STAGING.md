# V-Farms Reservations — staging handoff

**Repo:** `/root/karyuk-cc` (runtime). Frontend catalog lives in `/root/karyuk` (`apps/web/src/lib/catalog.ts`) — those `MODULE_*` IDs are **UI screens**, not karyuk-cc service modules. Do not treat V03/V05/B04/B06 as repo module numbers.

## Ownership map (actual paths)

| Capability | Owning path / ID |
|---|---|
| AI Employees (Builder/publish) | `api/app/routers/employees.py`, `api/app/services/employees.py`, models `employees` / `employee_drafts` / `employee_versions` |
| Knowledge (website + draft) | `api/app/services/website_knowledge.py`, `api/app/services/employee_knowledge.py`, draft fields `website_url` / `website_knowledge` |
| Calls list | `api/app/routers/platform.py` `GET /v1/workspaces/{id}/calls`; model `calls` |
| Outpero post-call webhook (Phase 1) | `POST /v1/webhooks/outpero/inbound/{connection_key}` — `api/app/routers/outpero.py`, `api/app/services/outpero/inbound_import.py` |
| Outpero Custom API actions | `POST /v1/webhooks/outpero/{workspace_id}/actions/*` — same router; auth `X-Outpero-Action-Secret` |
| Business / booking requests | `voice_booking_requests` via `api/app/services/voice/voice_booking_requests.py` + V-Farms actions `api/app/services/vfarms/` |
| UI screens (catalog only) | `/root/karyuk/apps/web/src/lib/catalog.ts` — e.g. MODULE_13 employees, MODULE_16 knowledge, MODULE_24 calls |

## Phase 1 call import QA

| Item | Status |
|---|---|
| Endpoint | `https://karyuk.wayfinderops.com/v1/webhooks/outpero/inbound/harish-staging` — **unchanged** |
| Binding | workspace `b96e99eb-2bda-4bdd-9aa9-ba9bc43762e3`, DID `+919000017599`, employee slug `2p5dFQKubqRMsuYMOdzPTg` |
| Send test | HTTP **200** (`test-e51f1a8c`) — **not** real-call evidence |
| **Phase 1 real-call QA** | **pending** — no operator-provided answered inbound call time + Outpero call ID matched to exactly one inbound Calls row |
| Sensitive content | Phase-1 allowlist strips transcript / recording / summary / captured on import |
| MODULE_COMPLETE | **not** claimed |

## V-Farms knowledge verified on call

| Item | Status |
|---|---|
| Source | `https://vfarms.in/` dated snapshot in employee draft (`marker: vfarms_reservations_staging_v1`) |
| Employee | `8e6c2dd9-7a10-4756-8c89-b74636ae91f4` — **draft revision 4** (not published / not on live DID) |
| Published version | none (intentionally staged; quote-only) |
| Outpero runtime sync | **No supported API** to push KARYUK draft → Harish script. Operator must paste training text / Custom API actions into Outpero (or a **separate** staging employee). Do **not** overwrite live Harish until reviewed. |
| FAQ on real test call | **pending** operator |

## Verified website contract (no online payment)

Website submit path (from `vfarms.in` booking frontend):

1. Required guest fields: **guestName, guestEmail, guestPhone** (+ `termsAccepted: true`)
2. Operations on submit: **`POST /api/bookings/hold`** then **`POST /api/bookings/confirm`** `{ bookingId }`
3. Confirmed proof: confirm JSON **`status == "confirmed"`** and reservation reference from hold `booking_reference` (success UI: “Booking confirmed / Your stay is secured / Reference …”)
4. Hold alone is **not** confirmed. Quote / HTTP 200 / hold success alone are **not** confirmed.
5. Payment UI exists but is **paused**; active path is “Confirm booking without payment.” Voice must **not** redirect to checkout or invent `pending_payment`.

## V-Farms voice booking QA

| Item | Status |
|---|---|
| Authoritative APIs | `GET /api/availability/calendar`, `POST /api/bookings/quote`, `POST /api/bookings/hold`, `POST /api/bookings/confirm` on `https://vfarms.in` |
| Read path (live) | **proven** — `check_stay_availability` returned `quote_ready` / `unavailable` |
| Write path | **`VFARMS_BOOKING_WRITES_ENABLED=false`** — no live hold/confirm against inventory |
| Payment | **None** in website flow — voice matches that |
| Confirmed speech | Only when confirm returns `status=confirmed` + reference |
| Sandbox | **None available** — fixture/unit tests only for confirm path |
| **Voice booking QA** | **pending** — no real staging call created a reservation verified in an authorized sandbox |

### Deployed staging action URLs

Workspace `b96e99eb-2bda-4bdd-9aa9-ba9bc43762e3`:

```
https://karyuk.wayfinderops.com/v1/webhooks/outpero/b96e99eb-2bda-4bdd-9aa9-ba9bc43762e3/actions/check_stay_availability
https://karyuk.wayfinderops.com/v1/webhooks/outpero/b96e99eb-2bda-4bdd-9aa9-ba9bc43762e3/actions/create_stay_reservation
https://karyuk.wayfinderops.com/v1/webhooks/outpero/b96e99eb-2bda-4bdd-9aa9-ba9bc43762e3/actions/create_staff_followup
```

**Secret reference names (values not printed):**

- Post-call: `OUTPERO_INBOUND_WEBHOOK_SECRET` / connection `harish-staging.signing_secret`
- Mid-call actions: Outpero agent `action_secret` (header `X-Outpero-Action-Secret`) — **not** the post-call signing secret
- Flags: `VFARMS_ACTIONS_ENABLED`, `VFARMS_BOOKING_WRITES_ENABLED`

### Outpero dashboard steps (Custom API) — quote-only default

1. Prefer a **separate staging Outpero employee** (do not overwrite live Harish script).
2. **Actions → During the call → Custom API** — for quote-only staging attach **only**:
   - `check_stay_availability`
   - `create_staff_followup`
3. Do **not** attach `create_stay_reservation` while `VFARMS_BOOKING_WRITES_ENABLED=false` and no authorized sandbox exists. The endpoint remains for fixture tests only.
4. Header: `X-Outpero-Action-Secret: <agent action_secret>` (from Karyuk Outpero agent record; optional `X-Outpero-Agent-Slug: 2p5dFQKubqRMsuYMOdzPTg`).
5. Map `check_in`/`checkIn`, `check_out`/`checkOut`, `guest_count`/`guests`/`adults` for availability; map reason/dates/notes/phone for staff follow-up.
6. Keep post-call webhook on `harish-staging` as Flat JSON / Every call; do not rotate its secret for this task.
7. After an authorized sandbox + writes approval, separately attach `create_stay_reservation` with `quote_ref`, guest fields, `caller_confirmed`, and stable `attempt_key`.

### Operator test script (when writes approved)

> “I’d like to book the whole resort. Check-in is [approved test date], checkout is [approved test date], and we’re [guest count] guests. What is the total?”

After the agent reads exact dates and total, provide name/email/phone, then say **“Yes, book it.”** With writes disabled, expect `writes_blocked` + staff follow-up (not a live reservation). When writes are separately approved, verify the V-Farms `booking_reference` in source, then match one Outpero call in KARYUK Calls. Also test unavailable / decline → no reservation.

## Files / migrations changed

- `api/alembic/versions/20261121_0011_vfarms_stay_quotes.py`
- `api/app/models/vfarms.py`
- `api/app/services/vfarms/{__init__,client,actions}.py`
- `api/app/routers/outpero.py` (action routes + status URLs)
- `api/app/config.py` (V-Farms flags)
- `api/scripts/seed_vfarms_reservations_employee.py`
- `api/tests/test_vfarms_actions.py`
- `docs/OUTPERO_INBOUND_PHASE1_STAGING.md` (QA pending note)
- `docs/VFARMS_RESERVATIONS_STAGING.md` (this file)

## Tests run

```
python -m unittest tests.test_vfarms_actions tests.test_outpero_inbound_phase1
```

**OK** (workspace isolation, ambiguous/invalid dates, unavailable, expired quote, price change, decline, duplicate attempt, writes_blocked, pending_payment without false confirm, staff follow-up).

## Blockers

1. **Phase 1 real-call QA** — needs operator answered inbound call (time + Outpero call ID).
2. **Outpero knowledge/script sync** — no API; operator paste required (quote-only: availability + staff follow-up only); FAQ-on-call pending.
3. **Live voice booking writes** — no authorized sandbox; keep `vfarms_booking_writes_enabled=false`; do not attach `create_stay_reservation` on the answered quote-only route.
4. **Booking E2E QA** — blocked until sandbox + writes approval; website path remains hold→confirm with **no** online payment step.
