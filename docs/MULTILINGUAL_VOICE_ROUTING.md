# Multilingual Exotel speech routing (karyuk-cc)

## Active PSTN worker

| Channel | Process | Path |
|---------|---------|------|
| Phone | `uvicorn` :8010 | `WebSocket /v1/ws/exotel/voice/{call_id}` |
| Browser sandbox | Vite web app | Not the phone worker |

## Speech stack by locale

| Locale | STT / TTS | Conversation LLM |
|--------|-----------|------------------|
| `te-IN` | **Sarvam** (Saaras + Bulbul @ 8 kHz) | Sarvam 105B |
| `hi-IN`, `en-IN` | **Sarvam** (same stack, locale from `conversation_language`) | Sarvam 105B |

Language switches on explicit phrases (e.g. `తెలుగులో చెప్పండి`, `हिंदी में`) at turn boundaries; stale TTS is cleared via Exotel `clear`.

Each call emits a redacted `session_trace` JSON log line (`trace_id`, `build_sha`, `speech_stack`, models, `knowledge_revision`).

## Verification status (dev)

| Check | Result |
|-------|--------|
| Speech route unit tests | PASS |
| Inbound two-way handset | NOT VERIFIED (authorized dial required) |
| LiveKit on Exotel | Not used (Sarvam only for te/hi/en) |
| Document revision on PSTN | NOT VERIFIED |
| Outbound Connect Voice AI | NOT VERIFIED |

## Commands

```bash
cd /root/karyuk-cc/api
source .venv/bin/activate
python -m unittest discover -s tests -p 'test_*.py' -q
```