from app.config import Settings, get_settings


def resolved_inbound_voice_mode(settings: Settings | None = None) -> str:
    """livekit | exotel_gemini | sarvam"""
    s = settings or get_settings()
    mode = (s.inbound_voice_mode or "auto").strip().lower()
    if mode in ("livekit", "exotel_gemini", "sarvam"):
        return mode
    if s.sarvam_api_key.strip():
        return "sarvam"
    if s.gemini_api_key.strip():
        return "exotel_gemini"
    if s.livekit_sip_uri.strip() and s.inbound_dial_livekit:
        return "livekit"
    return "exotel_gemini"


def use_sarvam_inbound_voice(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return resolved_inbound_voice_mode(s) == "sarvam" and bool(s.sarvam_api_key.strip())