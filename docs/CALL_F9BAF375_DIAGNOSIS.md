# Call diagnosis `f9baf375` / trace `a3e4471f` (~20:10 IST)

## Root cause

**False Hindi reply on a Telugu employee line** — not clipped Telugu audio.

| Step | What happened |
|------|----------------|
| Greeting | Telugu Bulbul TTS OK (`te-IN`, Sarvam) |
| Early audio | Echo/noise → empty STT, `music`, Tamil `ஆ` correctly **rejected** |
| First “accepted” turn | Sarvam STT returned **~13 chars Hindi** (`text_len=13`) with tag `hi-IN` |
| Language | Session used **STT language tag + short Devanagari** without a real question |
| Reply | Sarvam chat + **Hindi TTS** — caller likely spoke Telugu or was silent |
| After | Many `hello` / `music` / empty STT — **real speech never became a full turn** |

The caller did **not** receive an answer to their intent; the agent responded to **STT hallucination / echo**.

## Fix (this pass)

- Reject short Devanagari on Telugu-default lines (`hindi_noise_telugu_line`).
- Do **not** lock conversation language from Sarvam `detected` alone — **transcript script only**.
- Ignore STT lang tag for `resolve_call_language` when transcript &lt; 22 chars.
- Allow Telugu short acks (`అవును`, `సరే`).
- Shorter playback tail (0.28s) so caller can speak right after greeting.
- AI disclosure once in greeting (Telugu/Hindi/English).
- Redacted `turn_rejected reason=…` logs.

## Retest status

| Check | Result |
|-------|--------|
| `test_f9baf375_regression` (false Hindi blocked) | **PASS** |
| `test_call_turn_policy` | **PASS** |
| Sarvam e2e te/hi/en | **PASS** |
| Same handset live call after fix | **NOT VERIFIED** (dial 0404590002) |

Place a **new** call; logs should show `turn_rejected` for echo and `accepted=1` + Telugu reply for a full Telugu question.