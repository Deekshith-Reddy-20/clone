from __future__ import annotations

import base64
import io
import logging
import re
import time
import wave
from functools import lru_cache

from app.config import Settings, get_settings
from app.services.voice.pcm_audio import pcm_to_wav_bytes

logger = logging.getLogger(__name__)

SARVAM_CHAT_MODEL = "sarvam-105b-conversations"
STT_MODEL = "saaras:v4"
TTS_MODEL = "bulbul:v4-flash"
SARVAM_SPEECH_STACK = f"{STT_MODEL} · {TTS_MODEL}"

SUPPORTED_BCP47 = frozenset({"te-IN", "hi-IN", "en-IN"})
_ALLOWED_VOICE_LANGS = ("te-IN", "hi-IN", "en-IN")


def sarvam_configured(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return bool(s.sarvam_api_key.strip())


_quota_blocked_until = 0.0
_MEDIA_PROBE: tuple[bool, str, float] | None = None


def _quota_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "402" in msg or "insufficient_quota" in msg or "no credits" in msg


def mark_sarvam_quota_exhausted() -> None:
    global _quota_blocked_until, _MEDIA_PROBE
    _quota_blocked_until = time.monotonic() + 180.0
    _MEDIA_PROBE = (False, "insufficient_quota", time.monotonic())


def sarvam_media_ready(settings: Settings | None = None, *, probe: bool = False) -> tuple[bool, str]:
    """Return (ready, reason). Caches a short TTS probe when probe=True."""
    global _MEDIA_PROBE
    s = settings or get_settings()
    if not sarvam_configured(s):
        return False, "missing_api_key"
    if time.monotonic() < _quota_blocked_until:
        return False, "insufficient_quota"
    if _MEDIA_PROBE and not probe:
        ok, reason, ts = _MEDIA_PROBE
        if time.monotonic() - ts < 120.0:
            return ok, reason
    if not probe:
        return True, ""
    pcm = tts_pcm_8k("ok", "en-IN", speaker="shubh", settings=s)  # maps to v4 persona
    ok = len(pcm) > 1000
    reason = "" if ok else "insufficient_quota"
    if not ok:
        mark_sarvam_quota_exhausted()
    _MEDIA_PROBE = (ok, reason, time.monotonic())
    return ok, reason


_cached_key: str = ""


@lru_cache(maxsize=1)
def _client():
    from sarvamai import SarvamAI

    global _cached_key, _quota_blocked_until, _MEDIA_PROBE
    key = get_settings().sarvam_api_key.strip()
    if not key:
        raise RuntimeError("SARVAM_API_KEY is not set")
    if key != _cached_key:
        _cached_key = key
        _quota_blocked_until = 0.0
        _MEDIA_PROBE = None
    return SarvamAI(api_subscription_key=key)


def resolve_reply_language(raw: str) -> str:
    r = (raw or "").strip()
    if r in SUPPORTED_BCP47:
        return r
    return language_bcp47_from_employee(r)


def language_bcp47_from_employee(language: str) -> str:
    n = (language or "").strip().lower()
    if "telugu" in n or n in ("te", "te-in"):
        return "te-IN"
    if "hindi" in n or n in ("hi", "hi-in"):
        return "hi-IN"
    return "en-IN"


def _has_telugu_script(text: str) -> bool:
    return any("\u0c00" <= ch <= "\u0c7f" for ch in text)


def _has_devanagari_script(text: str) -> bool:
    return any("\u0900" <= ch <= "\u097f" for ch in text)


def _has_tamil_script(text: str) -> bool:
    return any("\u0b80" <= ch <= "\u0bff" for ch in text)


def _has_kannada_script(text: str) -> bool:
    return any("\u0c80" <= ch <= "\u0cff" for ch in text)


def _has_malayalam_script(text: str) -> bool:
    return any("\u0d00" <= ch <= "\u0d7f" for ch in text)


def is_non_allowed_indic(text: str) -> bool:
    """Reject STT noise in scripts we do not speak on the phone."""
    return (
        _has_tamil_script(text)
        or _has_kannada_script(text)
        or _has_malayalam_script(text)
    )


def clamp_voice_lang(code: str | None, fallback: str = "en-IN") -> str:
    n = _normalize_detected_lang(code, fallback)
    return n if n in SUPPORTED_BCP47 else fallback


def sanitize_reply_for_lang(reply: str, lang: str, *, vertical: str = "general") -> str:
    """Bulbul + chat must stay in te-IN / hi-IN / en-IN only."""
    from app.services.voice.spoken_output import filter_caller_facing_reply

    lang = clamp_voice_lang(lang)
    text = filter_caller_facing_reply((reply or "").strip(), lang=lang)
    if not text:
        return _clarify_more(lang, vertical=vertical)
    lodging = vertical == "lodging"
    from app.services.voice.spoken_length import cap_spoken_reply

    if lang == "te-IN":
        if _has_telugu_script(text) or (_is_mostly_english_roman(text) and len(text) < 80):
            return cap_spoken_reply(text)
        if _has_devanagari_script(text):
            if vertical == "hospital":
                return "క్షమించండి అండి, తెలుగులో చెప్తాను. ఏ డాక్టర్ కావాలో చెప్పండి."
            return "క్షమించండి, తెలుగులో చెప్తాను. మీరు ఏ తేదీలకు రావాలనుకుంటున్నారు?"
        if lodging:
            return "సరే. మీ చెక్-ఇన్ తేదీ ఎప్పుడు?"
        return "సరే అండి, ఎలా సహాయం చేయగలను?"
    if lang == "hi-IN":
        if _has_devanagari_script(text):
            return cap_spoken_reply(text)
        if lodging:
            return "ठीक है, चेक-इन की तारीख बताइए?"
        return "बताइए, मैं कैसे मदद करूँ?"
    if _is_mostly_english_roman(text):
        return cap_spoken_reply(text)
    if not (_has_telugu_script(text) or _has_devanagari_script(text)):
        return cap_spoken_reply(text)
    if lodging:
        return "Sure — what date would you like to check in?"
    return "How can I help you today?"


_SPURIOUS_STT_SNIPPETS = frozenset(
    {
        "ha",
        "ha ji",
        "hmm",
        "hm",
        "music",
        "हाँ",
        "हां",
        "हाँ जी",
        "हां जी",
        "हम्म",
        "ह्म्म",
        "जी",
        "ਹਾਂ ਜੀ",
        "હા",
    }
)


_HINDI_REAL_QUESTION = re.compile(
    r"(कितनी|कितना|कब|कहाँ|क्या|फीस|fee|समय|खुलता|बंद|मिलेग|होग)",
    re.I,
)


def is_real_hindi_question(text: str) -> bool:
    t = (text or "").strip()
    if t in ("क्या बात है", "ठीक है सर", "हाँ जी सर"):
        return False
    return bool(_has_devanagari_script(t) and _HINDI_REAL_QUESTION.search(t) and len(t) >= 10)


def is_hindi_ack_noise(text: str) -> bool:
    """Repeated हाँ/जी/ठीक without a real question — common PSTN echo on Telugu lines."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t or not _has_devanagari_script(t):
        return False
    if _has_telugu_script(t):
        return False
    if len(t) > 48:
        return False
    core = re.sub(r"[\s,।!?.]+", " ", t).strip()
    words = [w for w in core.split() if w]
    if not words:
        return True
    ack = frozenset(
        {
            "हाँ",
            "हां",
            "जी",
            "हम्म",
            "ह्म्म",
            "ठीक",
            "सर",
            "जी",
            "ji",
            "ha",
            "haan",
        }
    )
    if all(re.sub(r"[^\u0900-\u097fa-zA-Z]", "", w.lower()) in ack or w in ack for w in words):
        return True
    if len(t) <= 22 and all(any(a in w for a in ("हाँ", "हां", "जी", "ठीक")) for w in words):
        return True
    return False


def is_spurious_stt_snippet(text: str) -> bool:
    """Single-word STT hallucinations / echo — do not switch language or treat as a full turn."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return True
    if is_non_allowed_indic(t):
        return True
    if t.lower() in ("music", "hello hello"):
        return True
    if t.lower() == "hello" and len(t) <= 6:
        return True
    norm = t.lower().rstrip(".,!?")
    if norm in _SPURIOUS_STT_SNIPPETS:
        return True
    if len(t) <= 14 and t in _SPURIOUS_STT_SNIPPETS:
        return True
    if len(t) <= 18 and _has_devanagari_script(t) and not any(ch.isdigit() for ch in t):
        compact = re.sub(r"[\s,\.!]+", " ", t).strip()
        if compact in _SPURIOUS_STT_SNIPPETS or len(compact) <= 6:
            return True
    if is_hindi_ack_noise(t):
        return True
    return False


def detect_language_from_text(text: str) -> str | None:
    """Infer te-IN / hi-IN / en-IN from script and common phrases."""
    t = (text or "").strip()
    if not t:
        return None
    if _has_telugu_script(t):
        return "te-IN"
    if _has_devanagari_script(t) and not is_spurious_stt_snippet(t):
        return "hi-IN"
    low = t.lower()
    if any(
        p in low
        for p in (
            "telugu",
            "తెలుగు",
            "telegu",
            "telugulo",
            "teluglo",
            "matladagalar",
            "matladagalara",
            "naku hindi",
            "hindi ardham",
            "hindi ardam",
            "shift to telugu",
            "speak telugu",
        )
    ):
        return "te-IN"
    if any(
        p in low
        for p in (
            "hindi",
            "हिंदी",
            "हिन्दी",
            "హిందీ",
            "హిందీలో",
            "hindi mein",
            "hindi lo",
            "shift to hindi",
            "speak hindi",
        )
    ):
        return "hi-IN"
    return None


def resolve_conversation_language(
    *,
    caller_text: str,
    conversation_language: str | None,
    employee_language: str | None,
) -> str:
    """Best language for the next reply (STT, script, explicit request, employee default)."""
    for candidate in (
        detect_language_from_text(caller_text),
        conversation_language,
        employee_language,
    ):
        if candidate:
            if candidate in SUPPORTED_BCP47:
                return candidate
            return language_bcp47_from_employee(candidate)
    return "en-IN"


def _is_mostly_english_roman(text: str) -> bool:
    letters = [c for c in (text or "") if c.isalpha()]
    if len(letters) < 4:
        return False
    latin = sum(1 for c in letters if ord(c) < 128)
    return latin / len(letters) > 0.9


def resolve_call_language(
    *,
    caller_text: str,
    conversation_language: str | None,
    employee_language: str | None,
    stt_language: str | None = None,
) -> str:
    """Reply + TTS — only te-IN, hi-IN, en-IN."""
    emp = clamp_voice_lang(language_bcp47_from_employee(employee_language or ""), "en-IN")
    from_text = detect_language_from_text(caller_text)
    t = (caller_text or "").strip()

    if _has_telugu_script(t) or from_text == "te-IN":
        return "te-IN"
    if conversation_language == "te-IN" and _is_mostly_english_roman(t) and len(t) < 160:
        return "te-IN"
    if emp == "te-IN" and (conversation_language == "te-IN" or stt_language == "te-IN"):
        if _is_mostly_english_roman(t) and not _has_devanagari_script(t):
            return "te-IN"
    if _is_mostly_english_roman(t) and len(t) >= 8:
        return "en-IN"
    if _has_devanagari_script(t) and not is_spurious_stt_snippet(t) and not is_hindi_ack_noise(t):
        if len(t) >= 28 or is_real_hindi_question(t):
            return "hi-IN"

    stt_hint = stt_language
    if stt_hint and len(t) < 22:
        stt_hint = None
    polluted_conv = conversation_language
    if emp == "te-IN" and polluted_conv == "hi-IN" and not _has_devanagari_script(t):
        polluted_conv = "te-IN"

    if emp == "te-IN":
        return clamp_voice_lang(polluted_conv or stt_hint, "te-IN")
    if emp == "hi-IN":
        return clamp_voice_lang(conversation_language or stt_hint, "hi-IN")
    return clamp_voice_lang(conversation_language or stt_hint, "en-IN")


def avoid_repeat_reply(
    reply: str,
    last_reply: str | None,
    *,
    booking_active: bool = False,
) -> str:
    """Same words twice get a short new sentence of the same reply.

    A booking status repeat stays the real state. It is never rewritten into
    a dates-and-people recap.
    """
    if not last_reply or not reply or reply.strip() != last_reply.strip():
        return reply
    if _has_telugu_script(reply):
        return f"మళ్ళీ చెప్తాను అండి. {reply.strip()}"
    if _has_devanagari_script(reply):
        return f"फिर से बता देता हूँ जी। {reply.strip()}"
    return f"Again — {reply.strip()}"


def _normalize_detected_lang(code: str | None, fallback: str) -> str:
    if code and code in SUPPORTED_BCP47:
        return code
    if code and code.startswith("te"):
        return "te-IN"
    if code and code.startswith("hi"):
        return "hi-IN"
    if code and code.startswith("en"):
        return "en-IN"
    return fallback if fallback in SUPPORTED_BCP47 else "en-IN"


def compose_employee_context(
    brief: str,
    website_knowledge: str | None = None,
    *,
    website_url: str | None = None,
    natural_spoken: bool = True,
    vertical: str = "general",
) -> str:
    base = (brief or "Help callers using only the published business information below.").strip()
    parts = [
        "INTERNAL PLAYBOOK (never read aloud — answer only from these facts):",
        base,
    ]
    if website_url and str(website_url).strip():
        parts.append(f"Business website: {str(website_url).strip()}")
    web = (website_knowledge or "").strip()
    if web:
        parts.append(
            "PUBLISHED FACTS (location, hours, services, pricing; never invent):\n" + web[:4500]
        )
    if natural_spoken:
        parts.append(
            "You are at the front desk on a live call right now — answer like the real office "
            "staff: warm, sure, short sentences; natural అండి in Telugu. Use only the facts above "
            "(refreshed each turn). If a detail is missing, apologize and say it is not on file."
        )
        if vertical == "lodging":
            parts.append(
                "Lodging only: remember check-in, check-out, guest count; one question at a time."
            )
        elif vertical == "hospital":
            parts.append(
                "Hospital only: OP appointments (doctor/department, date, time, callback). "
                "Never ask hotel check-in, checkout, or guest count."
            )
        else:
            parts.append(
                "Answer any business question from published facts first. "
                "Start bookings or appointments only when the caller asks."
            )
    return "\n\n".join(parts)


def _employee_system_prompt(
    brief: str,
    *,
    reply_language: str,
    website_knowledge: str | None = None,
    website_url: str | None = None,
    natural_spoken: bool = True,
    vertical: str = "general",
) -> str:
    from app.services.voice.employee_playbook import agent_name_from_brief
    from app.services.voice.spoken_policy import build_reception_system_prompt

    facts = compose_employee_context(
        brief,
        website_knowledge,
        website_url=website_url,
        natural_spoken=natural_spoken,
        vertical=vertical,
    )
    biz = business_name_from_context(brief=brief, website_knowledge=website_knowledge or "")
    who = agent_name_from_brief(brief) or "Maya"
    lang = clamp_voice_lang(reply_language, "en-IN")
    return build_reception_system_prompt(
        agent_name=who,
        business_name=biz or "the business",
        facts=facts,
        reply_language=lang,
        vertical=vertical,
    )


def complete_chat(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 180,
    temperature: float = 0.4,
    settings: Settings | None = None,
) -> str:
    """One Sarvam chat completion. Empty string when the key is missing or the call fails."""
    s = settings or get_settings()
    if not sarvam_configured(s):
        return ""
    try:
        response = _client().chat.completions(
            model=SARVAM_CHAT_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return str(response.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.warning("Sarvam chat failed: %s", exc)
        return ""


def generate_agent_reply(
    *,
    employee_brief: str,
    caller_text: str,
    history: list[dict[str, str]],
    reply_language: str = "en-IN",
    website_knowledge: str | None = None,
    website_url: str | None = None,
    natural_spoken: bool = True,
    vertical: str = "general",
    system_prompt: str | None = None,
    settings: Settings | None = None,
) -> str:
    s = settings or get_settings()
    brief = compose_employee_context(
        employee_brief,
        website_knowledge,
        website_url=website_url,
        natural_spoken=natural_spoken,
        vertical=vertical,
    )
    user = (caller_text or "").strip() or "Hello"
    lang = clamp_voice_lang(reply_language, "en-IN")

    if not sarvam_configured(s):
        return _clarify_more(lang, vertical=vertical)

    sys_content = (system_prompt or "").strip() or _employee_system_prompt(
        employee_brief,
        reply_language=lang,
        website_knowledge=website_knowledge,
        website_url=website_url,
        natural_spoken=natural_spoken,
        vertical=vertical,
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": sys_content}]
    for turn in history[-10:]:
        role = turn.get("role")
        if role == "user":
            messages.append({"role": "user", "content": turn.get("text", "")[:500]})
        elif role == "assistant":
            messages.append({"role": "assistant", "content": turn.get("text", "")[:500]})
    messages.append({"role": "user", "content": user[:500]})

    try:
        response = _client().chat.completions(
            model=SARVAM_CHAT_MODEL,
            messages=messages,
            temperature=0.48,
            max_tokens=96,
        )
        text = response.choices[0].message.content or ""
        reply = sanitize_reply_for_lang(str(text).strip(), lang, vertical=vertical)
        return reply if reply else _clarify_more(lang, vertical=vertical)
    except Exception as exc:
        logger.warning("Sarvam chat failed: %s", exc)
        return _clarify_more(lang, vertical=vertical)


def transcribe_pcm(
    pcm: bytes,
    *,
    hint_language: str = "en-IN",
    settings: Settings | None = None,
) -> tuple[str, str]:
    """Exotel 8 kHz mono PCM → (transcript, detected_bcp47)."""
    s = settings or get_settings()
    fallback = _normalize_detected_lang(hint_language, "en-IN")
    if not sarvam_configured(s) or len(pcm) < 1600:
        return "", fallback

    from app.services.voice.sarvam_streaming import transcribe_pcm_streaming

    t0_ws = time.perf_counter()
    ws_text, ws_lang = transcribe_pcm_streaming(pcm, hint_language=fallback)
    if ws_text.strip():
        logger.info(
            "Sarvam STT path=ws_stream ms=%.0f bytes=%d",
            (time.perf_counter() - t0_ws) * 1000,
            len(pcm),
        )
        return ws_text.strip(), ws_lang

    wav_bytes = pcm_to_wav_bytes(pcm)
    t0_rest = time.perf_counter()
    try:
        result = _client().speech_to_text.transcribe(
            file=("caller.wav", wav_bytes, "audio/wav"),
            model=STT_MODEL,
            mode="codemix",
            language_code="unknown",
        )
        text = (result.transcript or "").strip()
        lang = _normalize_detected_lang(result.language_code, fallback)
        if text:
            logger.info(
                "Sarvam STT path=rest ms=%.0f bytes=%d",
                (time.perf_counter() - t0_rest) * 1000,
                len(pcm),
            )
            return text, lang
    except Exception as exc:
        if _quota_error(exc):
            mark_sarvam_quota_exhausted()
        code = ""
        body = str(exc)
        if _quota_error(exc) or "402" in body:
            code = "insufficient_quota"
        elif hasattr(exc, "status_code"):
            code = f"http_{getattr(exc, 'status_code')}"
        logger.warning(
            "Sarvam STT REST failed provider_code=%s err=%s",
            code or "unknown",
            type(exc).__name__,
        )

    return "", fallback


def _wav_b64_to_pcm(wav_bytes: bytes) -> bytes:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wfile:
        if wfile.getsampwidth() != 2 or wfile.getnchannels() != 1:
            logger.warning("Unexpected Sarvam WAV format %s ch", wfile.getnchannels())
        frames = wfile.readframes(wfile.getnframes())
        rate = wfile.getframerate()
        if rate == 8000:
            return frames
        if rate == 16000 and len(frames) >= 4:
            # Simple decimation 16k → 8k for telephony playback
            samples = memoryview(frames).cast("h")
            return bytes(samples[i] for i in range(0, len(samples), 2))
        return frames


def tts_pcm_8k(
    text: str,
    language_code: str,
    *,
    speaker: str | None = None,
    settings: Settings | None = None,
    rest_only: bool = False,
) -> bytes:
    s = settings or get_settings()
    if not sarvam_configured(s) or not (text or "").strip():
        return b""
    lang = _normalize_detected_lang(language_code, "en-IN")
    snippet = text.strip()[:1500]
    from app.services.voice.voice_catalog import resolve_bulbul_speaker_for_lang

    spk = resolve_bulbul_speaker_for_lang(speaker or "shubh", lang, tts_model=TTS_MODEL)
    if len(snippet) <= 220:
        pcm = _tts_pcm_8k_rest_cached(snippet, lang, spk)
    else:
        pcm = _tts_pcm_8k_rest(snippet, lang, spk, settings=s)
    if len(pcm) > 1000:
        return pcm
    if rest_only:
        return pcm
    # Long-form only: WS can add 30–60s connect latency on cold starts.
    if len(snippet) > 400:
        from app.services.voice.sarvam_streaming import tts_pcm_8k_streaming

        ws_pcm = tts_pcm_8k_streaming(snippet, lang, speaker=spk)
        if len(ws_pcm) > 1000:
            return ws_pcm
    return pcm


@lru_cache(maxsize=96)
def _tts_pcm_8k_rest_cached(snippet: str, lang: str, spk: str) -> bytes:
    return _tts_pcm_8k_rest(snippet, lang, spk, settings=None)


def _tts_pcm_8k_rest(
    snippet: str,
    lang: str,
    spk: str,
    *,
    settings: Settings | None = None,
) -> bytes:
    s = settings or get_settings()
    if not sarvam_configured(s):
        return b""
    try:
        kwargs: dict = {
            "text": snippet,
            "language_code": lang,
            "model": TTS_MODEL,
            "speech_sample_rate": 8000,
            "output_audio_codec": "wav",
            "pace": 1.05,
            "speaker": spk,
        }
        out = _client().text_to_speech.convert(**kwargs)
        if not out.audios:
            return b""
        wav_bytes = base64.b64decode(out.audios[0])
        return _wav_b64_to_pcm(wav_bytes)
    except Exception as exc:
        if _quota_error(exc):
            mark_sarvam_quota_exhausted()
        logger.warning("Sarvam TTS REST failed: %s", exc)
        return b""


def _clarify_more(lang: str, *, vertical: str = "general") -> str:
    more = {
        "te-IN": "క్షమించండి అండి, మరోసారి చెప్పగలరా?",
        "hi-IN": "माफ़ कीजिए, क्या आप दोबारा बता सकते हैं?",
        "en-IN": "Could you tell me a bit more?",
    }
    if vertical == "hospital" and lang == "te-IN":
        return "సరే అండి, ఎలా సహాయం చేయగలను?"
    return more.get(lang, more["en-IN"])


def is_clarify_fallback(reply: str, lang: str, *, vertical: str = "general") -> bool:
    """Generic 'say again' lines — caller should get grounded facts or booking instead."""
    r = (reply or "").strip()
    if not r:
        return True
    return r.strip() == _clarify_more(lang, vertical=vertical).strip()


def business_name_from_context(*, brief: str = "", website_knowledge: str = "") -> str:
    for blob in (brief, website_knowledge):
        text = (blob or "").strip()
        if not text:
            continue
        low = text.lower()
        if "v farms" in low or "vfarms" in low:
            return "V Farms Resort"
        m = re.search(
            r"\b((?:[A-Z][A-Za-z0-9&'\-]+(?:\s+|[\s])){1,6})"
            r"(?:Hospital|Clinic|Resort|Hotel|Farm|Spa|Homestay)\b",
            text,
        )
        if m:
            return m.group(0).strip()
        m = re.search(
            r"\b(?:[A-Z][A-Za-z0-9&'\-]+\s+){0,5}"
            r"(?:Resort|Hotel|Farm|Clinic|Spa|Homestay|Center|Centre)\b",
            text,
        )
        if m:
            return m.group(0).strip()
    return ""


def opening_greeting_for_employee(
    *,
    employee_language: str,
    brief: str = "",
    website_knowledge: str = "",
    phone: bool = False,
) -> tuple[str, str]:
    """Returns (greeting_text, voice_lang) — only te / hi / en-IN."""
    name = business_name_from_context(brief=brief, website_knowledge=website_knowledge)
    biz = name or "our team"
    emp = clamp_voice_lang(language_bcp47_from_employee(employee_language), "en-IN")
    if emp == "te-IN":
        if phone:
            who = biz or "మా ఆసుపత్రి"
            return (
                f"నమస్కారం! {who} నుంచి మాట్లాడుతున్నాను. ఎలా సహాయం చేయాలి?",
                "te-IN",
            )
        return (
            f"నమస్కారం! {biz} నుంచి మాట్లాడుతున్నాను. నేను మీ AI అసిస్టెంట్. చెప్పండి, ఎలా సహాయం చేయాలి?",
            "te-IN",
        )
    if emp == "hi-IN":
        if phone:
            return (f"नमस्ते, {biz} से बात कर रहा हूँ। मैं कैसे मदद करूँ?", "hi-IN")
        return (
            f"नमस्ते, {biz} में आपका स्वागत है। मैं AI सहायक हूँ। मैं आपकी कैसे मदद करूँ?",
            "hi-IN",
        )
    if phone:
        return (f"Hello, thanks for calling {biz}. How can I help?", "en-IN")
    return (
        f"Welcome to {biz}. I'm an AI assistant. How can I help you today?",
        "en-IN",
    )


def opening_greeting_english(*, brief: str = "", website_knowledge: str = "") -> str:
    """Legacy English greeting."""
    return opening_greeting_for_employee(employee_language="English", brief=brief, website_knowledge=website_knowledge)[0]


def greeting_text(brief: str, language_code: str) -> str:
    lang = _normalize_detected_lang(language_code, "en-IN")
    templates = {
        "te-IN": "నమస్కారం, మీకు ఎలా సహాయం చేయగలను?",
        "hi-IN": "नमस्ते, मैं आपकी कैसे मदद कर सकता हूँ?",
        "en-IN": "Hello, thanks for calling. How can I help you today?",
    }
    return templates.get(lang, templates["en-IN"])