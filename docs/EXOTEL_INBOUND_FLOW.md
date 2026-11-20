# Exotel inbound (Karyuk `exotel_gemini`)

## Correct webhook

```
https://<PUBLIC_API_BASE_URL>/v1/webhooks/exotel/inbound
```

Example: `https://guide-mushily-condense.ngrok-free.dev/v1/webhooks/exotel/inbound`

API must return **ExoML / Twilio-style XML** (`<Response><Say>…<Gather>…`).

## Full human-like AI (recommended with your Voicebot applet)

1. Flow: **Call Start → Voicebot** (no Hangup after it).
2. Voicebot URL:
   `https://<ngrok>/v1/webhooks/exotel/voicebot`
   (Exotel GETs this, then opens the `wss://` URL we return.)
3. For **Telugu / Hindi / Indian English**, set `.env`:
   - `INBOUND_VOICE_MODE=sarvam`
   - `SARVAM_API_KEY=…` (from [Sarvam](https://docs.sarvam.ai))
   - Uses Saaras STT (codemix) + `sarvam-105b-conversations` + Bulbul TTS at 8 kHz — no ffmpeg needed.
   - Offline listen test: `api\.venv\Scripts\python.exe scripts\sarvam_voice_smoke.py` (WAVs in `scripts/out/sarvam-smoke/`).
4. Or `INBOUND_VOICE_MODE=exotel_gemini` with `GEMINI_API_KEY`, `edge-tts`, and **ffmpeg** on PATH.
5. Set each published employee’s **Language** (English / Hindi / Telugu) on Team — greeting and default reply language follow it; Saaras can auto-detect when the caller switches.
6. Publish your **employee brief** — the AI speaks as that person and answers from the brief.

## Do **not** use Voicebot URL pointed at `/inbound` (XML)

**Voicebot** (AgentStream) does **not** run Say/Gather XML. On call start it **GETs** your URL and expects:

```json
{ "url": "wss://your-stream-handler.example/session" }
```

Then Exotel opens a **WebSocket** for bidirectional audio. Karyuk `exotel_gemini` uses **HTTP XML** (Say + Gather + Gemini), not a media WebSocket.

If Voicebot is wired to `/v1/webhooks/exotel/inbound`, the call may answer briefly then fail or hang up.

## Recommended Exotel setup

### Option A — Direct URL on the ExoPhone (best when available)

1. **ExoPhones** → **04045900002** → incoming / voice settings.
2. Set **Voice URL** (or “When a call comes in”) to the Karyuk webhook above (GET or POST).
3. Save. Flow **1385345** may be bypassed.

(Exotel’s REST API often only accepts `my.exotel.com/.../exoml/start_voice/...` URLs; the **dashboard** may still allow a full `https://` URL.)

### Option B — App Builder flow (classic ExoML)

Use an applet that **fetches a URL and executes returned `<Response>` XML** (legacy exophone URL behaviour), **not** Voicebot or Stream.

- If your account only offers Voicebot in the flow: use **Option A** on the number, or ask Exotel support to allow an external Voice URL.
- Remove **Hangup** immediately after the webhook applet; Karyuk’s XML already loops (Gather) and ends with `<Hangup/>` when needed.

### Option C — Voicebot + Sarvam (production Telugu path)

1. Flow: **Call Start → Voicebot** (no Hangup after it).
2. Voicebot HTTP URL: `https://<PUBLIC_API_BASE_URL>/v1/webhooks/exotel/voicebot`
3. Karyuk returns `{"url": "wss://<host>/v1/ws/exotel/voice/<call_id>"}` — Exotel opens bidirectional audio.
4. Set `INBOUND_VOICE_MODE=sarvam` and `SARVAM_API_KEY` in `.env`; republish employee with **Shubh** (or chosen) voice.
5. Caddy must proxy `/v1/*` to `127.0.0.1:8010` (karyuk-cc worker).
6. Verify: `python api/scripts/e2e_inbound_connect.py --ws` from the server.

### Option D — LiveKit SIP

Use `INBOUND_VOICE_MODE=livekit`, LiveKit SIP, and `run-voice-agent.ps1`.

## Test

1. `.\serve-api.ps1` and `.\scripts\start-ngrok.ps1` (separate windows).
2. Call **0404590002** / **04045900002**.
3. API log: `Exotel inbound From=…` then `…/inbound/conversation/…`.
4. `.\scripts\diagnose-exotel-inbound.ps1`

## Empty flow (1385345) — what to drop on “Call Start”

### Full AI (Say + speech + Gemini) — preferred

Exotel App Builder **cannot** run Karyuk’s full `<Response>` XML from most applets.

1. Go to **Co-workers and Groups → ExoPhones → 04045900002 → Configure** (not only App Builder).
2. If you see **Voice URL** / **Incoming call URL**, set it to:
   `https://<ngrok>/v1/webhooks/exotel/inbound`
3. Leave flow **1385345** minimal (or a no-op Greeting) if Exotel requires an app to be attached.

Do **not** use: **Voicebot**, **Stream** (they need `wss://`).

### Quick test inside App Builder only (hear one line from Karyuk)

1. Drag **Greeting** onto **Call Start**.
2. Choose **URL** / “read text from URL” (not static text).
3. URL: `https://<ngrok>/v1/webhooks/exotel/inbound/greeting`
4. **Next**: optional **Hangup** (test only).
5. **SAVE** → call **0404590002**.

If you hear your employee brief, ngrok + API work. Switch to **direct Voice URL** (above) for the full conversation.

### Do not use for Karyuk

| Applet | Why |
|--------|-----|
| Voicebot / Stream | Expect JSON + WebSocket, not our XML |
| Connect | Routes to human numbers, not your API |
| Passthru | Only HTTP 200/302 routing, ignores Say/Gather XML body |