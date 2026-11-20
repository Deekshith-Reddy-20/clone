from app.config import Settings, get_settings
from app.services.phone import national_exophone_display

from .exotel import exotel_configured, map_exotel_status, place_outbound_connect
from .inbound_mode import resolved_inbound_voice_mode
from .livekit_svc import livekit_configured, room_name_for_call


def telephony_mode(settings: Settings | None = None) -> str:
    s = settings or get_settings()
    if s.telephony_provider == "simulate":
        return "simulated"
    if s.telephony_provider == "exotel" or (s.telephony_provider == "auto" and exotel_configured(s)):
        return "exotel"
    return "simulated"


def telephony_status_payload(settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    from app.services.voice.sarvam import sarvam_media_ready

    sarvam_ok, sarvam_reason = sarvam_media_ready(probe=True)
    return {
        "mode": telephony_mode(s),
        "exotel_configured": exotel_configured(s),
        "livekit_configured": livekit_configured(s),
        "public_api_base_url": s.public_api_base_url,
        "exotel_caller_id_set": bool(s.exotel_caller_id.strip()),
        "exotel_caller_id": s.exotel_caller_id.strip() or None,
        "exotel_dial_national": national_exophone_display(s.exotel_caller_id)
        if s.exotel_caller_id.strip()
        else None,
        "exotel_inbound_voice_url": f"{s.public_api_base_url.rstrip('/')}/v1/webhooks/exotel/inbound",
        "exotel_voicebot_resolve_url": f"{s.public_api_base_url.rstrip('/')}/v1/webhooks/exotel/voicebot",
        "livekit_sip_uri_set": bool(s.livekit_sip_uri.strip()),
        "inbound_voice_mode": resolved_inbound_voice_mode(s),
        "gemini_configured": bool(s.gemini_api_key.strip()),
        "sarvam_ready": sarvam_ok,
        "sarvam_status": sarvam_reason,
        "sarvam_speech_stack": __import__(
            "app.services.voice.sarvam", fromlist=["SARVAM_SPEECH_STACK"]
        ).SARVAM_SPEECH_STACK,
    }


__all__ = [
    "exotel_configured",
    "livekit_configured",
    "map_exotel_status",
    "place_outbound_connect",
    "room_name_for_call",
    "telephony_mode",
    "telephony_status_payload",
]