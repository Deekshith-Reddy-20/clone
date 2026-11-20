# Karyuk voice worker (LiveKit)

The API creates a LiveKit room per call (`karyuk-call-{call_id}`) with the employee brief in room metadata. Exotel inbound dials `LIVEKIT_SIP_URI` with `X-LiveKit-Room` set to that room name.

## Quick test (inbound, no Exotel outbound KYC)

**Default `INBOUND_VOICE_MODE=exotel_gemini`** — Exotel Say/Gather loop on the API; set `GEMINI_API_KEY` for LLM replies (rule-based fallback if empty). **No LiveKit SIP or voice worker required.**

1. `.\scripts\setup-inbound-test.ps1` — registers ExoPhone + prints webhook URL  
2. `.\scripts\start-inbound-stack.ps1` — API + ngrok (starts voice agent only when mode is `livekit`)  
3. Exotel → ExoPhone `04045900002` → applet URL: `{PUBLIC_API_BASE_URL}/v1/webhooks/exotel/inbound`  
4. Call the ExoPhone from your phone  
5. `.\scripts\run-full-integration.ps1` — automated smoke  

For **LiveKit** mode: set `INBOUND_VOICE_MODE=livekit`, `INBOUND_DIAL_LIVEKIT=true`, provision inbound trunk, run `.\scripts\run-voice-agent.ps1`, add `OPENAI_API_KEY` for full STT/LLM/TTS.

## LiveKit Cloud

### LiveKit Cloud (required for call to stay up)

1. **Telephony → Configuration** — note SIP FQDN (matches `LIVEKIT_SIP_URI`).
2. **Inbound trunk** — allow Exotel (or open IPs); number `+914045900002`.
3. **Dispatch rule — Callee** — room name = SIP `To` user part (we dial `sip:karyuk-call-{uuid}@{fqdn}`).
4. Run `.\scripts\start-inbound-stack.ps1` — **three separate windows** (API, ngrok, voice agent).

If the call drops after the greeting, LiveKit SIP is not accepting Exotel yet — see [Exotel + LiveKit trunking](https://support.exotel.com/support/solutions/articles/3000134145-livekit-and-exotel-sip-trunking-integration-guide) or set `INBOUND_DIAL_LIVEKIT=false` in `.env` to hold on Exotel audio while provisioning.