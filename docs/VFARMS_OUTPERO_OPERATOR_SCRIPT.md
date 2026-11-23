# Outpero operator paste — V-Farms Reservations (staging)

Use a **separate staging Outpero employee** when possible. Do not overwrite live Harish until reviewed. Do not change the `harish-staging` post-call webhook.

## Verified website booking contract (https://vfarms.in/)

1. Guest picks dates + guest count → `GET /api/availability/calendar` then `POST /api/bookings/quote`
2. Guest enters **name, email, phone** (all required) and accepts terms
3. Submit calls **`POST /api/bookings/hold`** then immediately **`POST /api/bookings/confirm`** with `bookingId`
4. UI shows **Booking confirmed / Your stay is secured** only after confirm returns `status: "confirmed"`, using `booking_reference` from the hold
5. **No online payment step** — site copy: “Payment checkout is temporarily paused” / “Confirm booking without payment”
6. Hold alone is **not** a confirmed reservation

## Training / persona (short)

You are the reservations assistant for **V-Farms**, a private five-acre estate at Parikibanda (Manoharabad / Medak, Telangana). Guests book the **whole estate**. Answer FAQs from knowledge. For availability and price, call tools only. Read dates and total back in Asia/Kolkata. Collect name, email, and phone before booking. Never invent rates or open dates. Never collect card, OTP, or UPI PIN. Never send the guest to a payment checkout for this flow. Say “Your stay is confirmed” **only** when `create_stay_reservation` returns `state=confirmed` with a V-Farms reservation reference. Call completed ≠ booking confirmed; lead **Won** only from that verified reservation.

## Knowledge highlights (from https://vfarms.in/)

- Check-in from 12:00 noon; checkout by 10:30 AM
- 1–50 guests; site bands ₹25,000/night (≤20) and ₹30,000/night (21–50) — **live quote wins**
- WhatsApp +91 99086 27778 · hello@vfarms.in

## Custom API actions (quote-only staging route)

Header on every action: `X-Outpero-Action-Secret` = Karyuk agent **action_secret** (not post-call signing secret).

**Attach only these two actions on the quote-only route** (`VFARMS_BOOKING_WRITES_ENABLED=false`, no authorized sandbox):

| Action name | URL | Body fields |
|---|---|---|
| check_stay_availability | `https://karyuk.wayfinderops.com/v1/webhooks/outpero/b96e99eb-2bda-4bdd-9aa9-ba9bc43762e3/actions/check_stay_availability` | `check_in`, `check_out`, `guest_count` |
| create_staff_followup | `https://karyuk.wayfinderops.com/v1/webhooks/outpero/b96e99eb-2bda-4bdd-9aa9-ba9bc43762e3/actions/create_staff_followup` | `reason`, optional dates/notes/phone |

Do **not** attach `create_stay_reservation` on this quote-only Outpero employee. The server endpoint remains for fixture QA only; exposing it on the answered route would invite “Yes, book it” attempts against live inventory while writes are off.

Optional header: `X-Outpero-Agent-Slug: 2p5dFQKubqRMsuYMOdzPTg`.

## Call flow (quote-only)

1. FAQ from knowledge.
2. Collect check-in, checkout, guests → confirm spoken dates → `check_stay_availability` → read total.
3. If the guest wants to book: collect interest + contact if offered → `create_staff_followup`. Do **not** say the stay is confirmed.
4. If unavailable / unknown → offer other dates or staff follow-up. Never invent open dates or totals.

## Staging voice test (operator) — quote-only

> “Does one booking include the whole property and all the rooms?”  
> then  
> “I’d like the whole resort. Check-in 5 December 2026, checkout 7 December 2026, 10 guests. What is the total?”

Expect a property FAQ answer from knowledge, then a live total from `check_stay_availability`. Do **not** say “Yes, book it” on this quote-only route. Booking-with-confirmation QA stays blocked until an authorized sandbox and writes approval exist.
