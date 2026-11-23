# Karyuk-CC Voice Agent — Handoff Report (for ChatGPT context)

**Date:** 2026-11-21 (IST) / 2026-11-20 (UTC)  
**Project path:** `/root/karyuk-cc`  
**Host:** Hetzner (`2.31.134.192`)  
**Public URL:** `https://karyuk.wayfinderops.com`  
**ExoPhone (manual test):** `04045900002` / `0404590002`  
**Repo note:** No reliable `.git` history in this tree for authorship; treat as staging/repl work.

---

## 1. What this system is

Inbound **Telugu/English codemix** voice receptionist for lodging (V Farms resort style):

- Exotel **Voicebot** applet → WSS media stream → Karyuk FastAPI
- **Sarvam** Saaras STT + Bulbul TTS (REST preferred; WS paths were hanging)
- LLM-first dialogue with **deterministic booking slot layer** for lodging stays
- Enquiry is **not a hard booking** — `create_booking` creates a **staff follow-up request** (availability confirm + callback)

---

## 2. Runtime / infra (current)

| Piece | Detail |
|--------|--------|
| API | `uvicorn app.main:app --host 127.0.0.1 --port 8010` |
| Env | `/root/karyuk-cc/.env` + `KARYUK_PSTN_STREAM=0` (stream path disabled; was hanging) |
| Logs | `/tmp/karyuk-cc-8010.log` |
| Health | `GET http://127.0.0.1:8010/health` and Caddy `/health` → 8010 |
| Caddy (docker `karyuk-caddy-1`) | `karyuk.wayfinderops.com` → `/v1/*` and `/health` reverse_proxy `127.0.0.1:8010` |
| Front (other) | Default site → `:3000`; some `/exotel/*` → `:8765` / media `:8767` (M05 demo paths — not the main Sarvam voicebot path) |
| Port conflict | Another process may bind `172.17.0.1:8010` (staging). **Live Exotel path needs `127.0.0.1:8010`.** If 8010 dies, public health 502 and calls drop. |

**Voicebot wiring (expected):**  
Flow: Call Start → Voicebot (no Hangup after). Voicebot URL hits Karyuk webhook which returns `{"url":"wss://…/v1/ws/exotel/voice/<call_id>"}`.

---

## 3. Goals the user asked for (and status)

### A. Natural turn-taking / input handling
**Problem:** Agent ignored caller audio; long silence; double TTS.  
**Done:**
- Energy / silence / utterance-end tuning in `exotel_voicebot_session.py`
- REST-first Sarvam STT; REST TTS (`rest_only` for PSTN)
- `KARYUK_PSTN_STREAM=0` — non-stream turn path
- Duplicate identical TTS reply skip
- Speak-once (no double `_speak`)

### B. Confirmation loop (“పెట్టమంటారా?” again after ఆ / Okay / పెట్టండి)
**Problem:** Short Telugu/English yes not treated as confirm; phone required before confirm blocked forever.  
**Done:**
- Expanded `confirmation_yes` / `slot_verbal_yes` (ఆ, హా, Okay అండి, పెట్టండి, …)
- Phone **not** required in `missing_booking_slots` before verbal confirm
- Soft post-confirm: “ఇంకా ఏ సహాయం కావాలా?” instead of re-reading the note forever (fixed after a bug where soft path was unreachable)

### C. Availability → nights → auto checkout
**User want:** Ask nights when checking availability; from nights compute checkout; don’t make caller invent checkout.  
**Done:**
- Slot order: `check_in` → `nights` → `guests` → confirm
- `extract_nights_answer` for bare `2`, `రెండు`, `2 nights`, etc. when last ask was nights
- `sync_checkout_from_nights`: `check_out = check_in + nights`
- Bare nights no longer mis-parsed as calendar day (was overwriting check-in to Dec 2, etc.)
- Prompt: never ask checkout date; ask nights instead
- `create_booking` no longer clears existing computed `check_out` on “ఆ”

**Still fragile:** LLM can still occasionally ask checkout if it escapes slot code; mitigated by code-owned slot turns + prompt.

### D. Auto end call after enquiry
**User asked once** to hang up after noting enquiry; then asked **why is it auto ending** / **still the same** → wanted it **off**.  
**Done (final):**
- **No auto-hangup** after `create_booking` / `check_availability` / confirm note
- Hangup only on clear goodbye phrases (`bye`, `అంతే చాలు`, …)
- Removed “thanks + booking_confirmed ⇒ hangup”
- Exotel hangup still closes WSS when hangup flag is true (for real bye)
- Important: some “call ended” events were **API down (8010 not listening)** → Caddy 502, not agent hangup

### E. Self-aware replies / less repetition / answer per user input
**User:** repeating words; be self-conscious; reply as per my answer.  
**Done:**
- Slot collection mostly **code-rendered**: ack only what was just filled + ask **one** next missing slot
- Unclear crumbs (`నెంబర్`, short ఆ) → short re-ask of the real missing slot; **no fake** “noted your number”
- `collapse_repeated_spoken` (word/sentence stutter)
- `avoid_repeat_reply` no longer prefixes “మళ్ళీ చెప్తాను” + same full line
- System prompt SELF-AWARE block: don’t invent notes; don’t re-ask filled slots; don’t ask check-in+checkout together

---

## 4. Booking flow (intended behavior now)

1. Caller asks availability / dates → capture **check-in** (relative dates via `voice_dates.resolve_dates`)
2. Ask **ఎన్ని nights?** → set `nights`, compute `check_out`
3. Ask **ఎంత మంది?** → `guest_count`
4. Readback: `{weekday date} check-in, N nights, G guests — ఇలా request పెట్టమంటారా?`
5. On yes → `create_booking` tool → voice booking request row + spoken note that team will confirm & call back
6. Stay on line → soft “ఇంకా ఏ సహాయం కావాలా?”
7. Hang up only if caller clearly says goodbye

**Slots file:** `api/app/services/voice/voice_booking_slots.py`  
**State:** `api/app/services/voice/booking_state.py` (`inbound_booking` blob)  
**Tools:** `api/app/services/voice/voice_tools.py`  
**LLM entry:** `api/app/services/voice/inbound_llm_engine.py`  
**Exotel session:** `api/app/services/voice/exotel_voicebot_session.py`

---

## 5. Key files touched (this workstream)

- `api/app/services/voice/exotel_voicebot_session.py` — listen gate, REST TTS, duplicate skip, hangup→`ws.close`
- `api/app/services/voice/sarvam.py` — REST STT/TTS; `avoid_repeat_reply` softened
- `api/app/services/voice/voice_booking_slots.py` — nights parse, checkout sync, slot-owned turns, soft follow-up, collapse repeats
- `api/app/services/voice/voice_dates.py` — nights → checkout apply
- `api/app/services/voice/booking_state.py` — yes-phrases (earlier)
- `api/app/services/voice/voice_tools.py` — preserve checkout; no hangup on note
- `api/app/services/voice/inbound_llm_engine.py` — slot hangup flag plumbing; thanks≠hangup; polish collapse
- `api/app/services/voice/inbound_conversation.py` — thanks≠hangup
- `api/app/services/voice/voice_system_prompt.py` — self-aware / no checkout ask
- `api/app/services/voice/call_turn_policy.py` — short ack / too-short tuning (earlier)
- Tests: `api/tests/test_booking_slots.py` (nights, soft confirm, progress ack, no fake note)

---

## 6. Recent live call snapshots (behavior evidence)

### Call `0d82bbd2` (after soft follow-up fix)
- Dates + guests → confirm → note → user “సరే” → **soft anything-else** (good)
- Earlier turns still had LLM inventing check-out ask / wrong “noted number” (before slot-owned mid-turns)

### Call `84a56288` / `c5e7104e` (older)
- Repeated note after confirm (soft path unreachable / hangup era)
- Asked checkout after nights already given
- First note sometimes showed `0 nights` then corrected (state race / checkout clear bug — addressed)

### Ops issue
- Restarting API sometimes left **127.0.0.1:8010 dead** while process looked alive or Caddy 502 → calls “auto end” from infrastructure, not dialogue policy

---

## 7. How to run / verify

```bash
# API
cd /root/karyuk-cc/api
set -a && source /root/karyuk-cc/.env && set +a
export KARYUK_PSTN_STREAM=0
.venv/bin/python3.12 .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010 --log-level info >> /tmp/karyuk-cc-8010.log 2>&1 &

curl -sS http://127.0.0.1:8010/health
curl -sS --resolve karyuk.wayfinderops.com:443:127.0.0.1 https://karyuk.wayfinderops.com/health -k

# Tests
cd /root/karyuk-cc/api && .venv/bin/python3 -m pytest tests/test_booking_slots.py -q
```

**Manual:** dial `04045900002`, ask availability for a date, give nights + guests, confirm with ఆ/పెట్టండి, then say సరే — expect soft follow-up, line stays open.

---

## 8. Open issues / next work (honest)

1. **LLM can still leak** checkout questions or long paraphrases on interrupt / non-slot turns — keep tightening guards.
2. **STT crumbs** (ఆ, Okay) mid-slot still need careful mapping; guests vs nights confusion when both are numbers.
3. **8010 process stability** — ensure only one listener on `127.0.0.1:8010`; watch for silent death after restarts.
4. **TTS “repeating words”** — text collapse added; if still heard, may be Bulbul/prosody or STT echo → barge-in/clear path.
5. **Product constraint earlier:** handoff asked not to invent git authorship; no product redesign for review — work has been setup + voice/booking reliability fixes.
6. User **does not want** auto hangup after enquiry (reverted). Only hang up on explicit bye.
7. Canvas handoff existed earlier (`karyuk-cc-handoff.canvas.tsx`) for UI handoff — this markdown is the ChatGPT-oriented narrative.

---

## 9. One-paragraph summary for ChatGPT

We are running karyuk-cc on Hetzner behind Caddy at karyuk.wayfinderops.com:8010 for Exotel Voicebot + Sarvam STT/TTS. Voice reliability was fixed with REST STT/TTS, silence/energy gates, and PSTN stream off. Lodging booking is slot-based (check-in → nights → guests → confirm → staff enquiry request); nights auto-compute checkout; short Telugu/English yes confirms; phone not required pre-confirm. Auto hangup after noting an enquiry was added then **removed** per user — calls stay open with a soft anything-else; goodbye-only hangup. Latest work makes the agent more self-aware: code-owned acks tied to what the caller actually said, one next question, less repeated lines. Main remaining risks are LLM leakage, STT short-ack ambiguity, and keeping 127.0.0.1:8010 alive for Exotel.

---

## 10. Suggested prompt when pasting into ChatGPT

> You are helping continue work on the Karyuk-CC Exotel/Sarvam lodging voice agent. Read the handoff report below. Do not re-introduce auto hangup after enquiry. Prefer code-owned booking slots over LLM inventing dates/checkout. Preserve Telugu-English codemix. Ask me which symptom to fix next if unclear.

*(Then paste this entire file.)*
