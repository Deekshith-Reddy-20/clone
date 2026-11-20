"""Sarvam STT/TTS/chat smoke — Telugu, Hindi, Indian English (no phone call).

Writes playable WAV files under scripts/out/sarvam-smoke/.
"""
from __future__ import annotations

import os
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "api"
ENV_FILE = ROOT / ".env"
OUT_DIR = Path(__file__).resolve().parent / "out" / "sarvam-smoke"

SAMPLES: list[tuple[str, str, str]] = [
    ("te-IN", "telugu-greeting.wav", "నమస్తే, కాల్ చేసినందుకు ధన్యవాదాలు. ఈ రోజు నేను మీకు ఎలా సహాయం చేయగలను?"),
    ("hi-IN", "hindi-greeting.wav", "नमस्ते, कॉल करने के लिए धन्यवाद। बताइए, मैं आपकी कैसे मदद कर सकता हूँ?"),
    (
        "en-IN",
        "indian-english-greeting.wav",
        "Hello, thanks for calling. I am happy to help — what would you like to know today?",
    ),
]

CHAT_PROMPTS: list[tuple[str, str]] = [
    ("te-IN", "నాకు టెస్ట్ డ్రైవ్ బుక్ చేయాలి."),
    ("hi-IN", "मुझे कल शाम चार बजे appointment चाहिए।"),
    ("en-IN", "Can you tell me your working hours?"),
]


def _load_env_file() -> None:
    if not ENV_FILE.is_file():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = val.strip()


def _pcm_to_wav_file(pcm: bytes, path: Path, *, rate: int = 8000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wfile:
        wfile.setnchannels(1)
        wfile.setsampwidth(2)
        wfile.setframerate(rate)
        wfile.writeframes(pcm)


def main() -> int:
    _load_env_file()
    if not os.environ.get("SARVAM_API_KEY", "").strip():
        print("SARVAM_API_KEY is missing. Add it to .env in the project root.", file=sys.stderr)
        return 1

    sys.path.insert(0, str(API))
    os.chdir(API)

    from app.services.voice.sarvam import generate_agent_reply, sarvam_configured, tts_pcm_8k

    if not sarvam_configured():
        print("Sarvam is not configured (SARVAM_API_KEY).", file=sys.stderr)
        return 1

    brief = (
        "You work at a friendly car dealership in Hyderabad. "
        "Test drives are free on weekdays 10 AM to 6 PM. "
        "Speak naturally on the phone."
    )

    print("Bulbul TTS (8 kHz) — open the WAV files to hear:")
    for lang, filename, text in SAMPLES:
        pcm = tts_pcm_8k(text, lang)
        if not pcm:
            print(f"  FAIL {lang} {filename}", file=sys.stderr)
            return 1
        out = OUT_DIR / filename
        _pcm_to_wav_file(pcm, out)
        print(f"  OK {lang} → {out}")

    print("\nsarvam-105b-conversations replies:")
    for lang, user_msg in CHAT_PROMPTS:
        reply = generate_agent_reply(
            employee_brief=brief,
            caller_text=user_msg,
            history=[],
            reply_language=lang,
        )
        print(f"  [{lang}] caller: {user_msg}")
        print(f"  [{lang}] agent: {reply}\n")
        safe = lang.replace("-", "_").lower()
        reply_pcm = tts_pcm_8k(reply, lang)
        if reply_pcm:
            _pcm_to_wav_file(reply_pcm, OUT_DIR / f"{safe}-agent-reply.wav")

    print(f"SARVAM_VOICE_SMOKE_OK → {OUT_DIR.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())