from __future__ import annotations

import logging

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


def gemini_configured(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return bool(s.gemini_api_key.strip())


def _employee_system_prompt(brief: str) -> str:
    return (
        "You ARE the business phone agent described below — speak in first person as a real human employee, "
        "not as an AI. Follow the brief for facts, offers, policies, and tone. "
        "Answer the caller's question directly using only information from the brief; if the brief does not cover it, "
        "say you will note it and a teammate will follow up — do not invent prices, dates, or promises. "
        "Use warm, natural spoken English (India-friendly). "
        "Replies for phone: usually 2–4 short sentences, under 70 words; one clarifying question when needed. "
        "Never mention Gemini, AI, or bots.\n\n"
        f"EMPLOYEE BRIEF:\n{brief}"
    )


def generate_agent_reply(
    *,
    employee_brief: str,
    caller_text: str,
    history: list[dict[str, str]],
    settings: Settings | None = None,
) -> str:
    """Spoken reply for inbound call — human-like, brief-driven."""
    s = settings or get_settings()
    brief = (employee_brief or "You are a helpful phone agent for this business.").strip()
    user = (caller_text or "").strip() or "Hello"

    if not gemini_configured(s):
        return (
            f"I understand. You said: {user[:100]}. "
            f"Based on our line: {brief[:160]}"
        )[:400]

    model = s.gemini_model.strip() or "gemini-2.5-flash"
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={s.gemini_api_key.strip()}"
    )
    contents: list[dict] = [{"role": "user", "parts": [{"text": _employee_system_prompt(brief)}]}]
    contents.append({"role": "model", "parts": [{"text": "Understood. I'll speak as that employee on the phone."}]})
    for turn in history[-10:]:
        role = "user" if turn.get("role") == "user" else "model"
        contents.append({"role": role, "parts": [{"text": turn.get("text", "")[:500]}]})
    contents.append({"role": "user", "parts": [{"text": user[:500]}]})

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                url,
                json={
                    "contents": contents,
                    "generationConfig": {"temperature": 0.65, "maxOutputTokens": 256},
                },
            )
        if response.status_code >= 400:
            logger.warning("Gemini HTTP %s %s", response.status_code, response.text[:200])
            return f"Thanks for explaining. {brief[:140]}"
        data = response.json()
        text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
        reply = str(text).strip()
        return reply[:420] if reply else "Tell me a bit more so I can help you properly."
    except Exception as exc:
        logger.warning("Gemini call failed: %s", exc)
        return f"I heard you. {brief[:120]}"


def generate_agent_reply_with_tools(
    *,
    system_prompt: str,
    caller_text: str,
    history: list[dict[str, str]],
    settings: Settings | None = None,
) -> tuple[str, list[dict]]:
    """Native Gemini function calling — returns (spoken_text, tool_calls)."""
    from app.services.voice.voice_tool_definitions import GEMINI_TOOL_DECLARATIONS

    s = settings or get_settings()
    if not gemini_configured(s):
        return generate_agent_reply(employee_brief=system_prompt, caller_text=caller_text, history=history), []
    model = s.gemini_model.strip() or "gemini-2.5-flash"
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={s.gemini_api_key.strip()}"
    )
    contents: list[dict] = [{"role": "user", "parts": [{"text": system_prompt}]}]
    contents.append({"role": "model", "parts": [{"text": "Understood."}]})
    for turn in history[-8:]:
        role = "user" if turn.get("role") == "user" else "model"
        contents.append({"role": role, "parts": [{"text": turn.get("text", "")[:500]}]})
    contents.append({"role": "user", "parts": [{"text": (caller_text or "Hello")[:500]}]})
    tool_calls: list[dict] = []
    try:
        with httpx.Client(timeout=35.0) as client:
            response = client.post(
                url,
                json={
                    "contents": contents,
                    "tools": [{"functionDeclarations": GEMINI_TOOL_DECLARATIONS}],
                    "generationConfig": {"temperature": 0.55, "maxOutputTokens": 180},
                },
            )
        if response.status_code >= 400:
            return "", tool_calls
        data = response.json()
        cand = (data.get("candidates") or [{}])[0]
        parts = (cand.get("content") or {}).get("parts") or []
        spoken = ""
        for part in parts:
            if part.get("text"):
                spoken += str(part["text"])
            fc = part.get("functionCall") or part.get("function_call")
            if fc:
                tool_calls.append({"name": fc.get("name", ""), "args": fc.get("args") or {}})
        return spoken.strip(), tool_calls
    except Exception as exc:
        logger.warning("Gemini tools call failed: %s", exc)
        return "", tool_calls


def transcribe_pcm_wav(pcm: bytes, settings: Settings | None = None) -> str:
    """Caller speech from 8 kHz mono PCM (Exotel Voicebot)."""
    s = settings or get_settings()
    if not gemini_configured(s) or len(pcm) < 1600:
        return ""
    from app.services.voice.pcm_audio import pcm_to_wav_bytes

    import base64

    wav_b64 = base64.b64encode(pcm_to_wav_bytes(pcm)).decode("ascii")
    model = s.gemini_model.strip() or "gemini-2.5-flash"
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={s.gemini_api_key.strip()}"
    )
    try:
        with httpx.Client(timeout=35.0) as client:
            response = client.post(
                url,
                json={
                    "contents": [
                        {
                            "parts": [
                                {
                                    "text": (
                                        "Transcribe what the caller said in this phone audio. "
                                        "Return only their words in English, nothing else."
                                    )
                                },
                                {"inline_data": {"mime_type": "audio/wav", "data": wav_b64}},
                            ]
                        }
                    ],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 120},
                },
            )
        if response.status_code >= 400:
            return ""
        data = response.json()
        text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
        return str(text).strip()
    except Exception as exc:
        logger.warning("Gemini transcribe failed: %s", exc)
        return ""