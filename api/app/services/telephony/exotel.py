import base64
import logging
from urllib.parse import urlencode

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

EXOTEL_STATUS_MAP = {
    "queued": "queued",
    "initiated": "dialing",
    "ringing": "ringing",
    "in-progress": "connected",
    "completed": "completed",
    "busy": "busy",
    "no-answer": "no_answer",
    "failed": "failed",
    "canceled": "canceled",
}


def _exotel_api_root(settings: Settings) -> str:
    if settings.exotel_api_base_url.strip():
        return settings.exotel_api_base_url.rstrip("/")
    if settings.exotel_subdomain.strip():
        sub = settings.exotel_subdomain.strip().removesuffix(".exotel.com")
        return f"https://{sub}.exotel.com"
    return ""


def exotel_configured(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return all(
        [
            _exotel_api_root(s),
            s.exotel_account_sid.strip(),
            s.exotel_api_key.strip(),
            s.exotel_api_token.strip(),
            s.exotel_caller_id.strip(),
        ]
    )


def map_exotel_status(raw: str) -> str:
    return EXOTEL_STATUS_MAP.get(raw.lower().replace("_", "-"), "queued")


def _auth_header(settings: Settings) -> str:
    token = base64.b64encode(
        f"{settings.exotel_api_key}:{settings.exotel_api_token}".encode()
    ).decode()
    return f"Basic {token}"


def _exotel_e164(phone: str) -> str:
    """Exotel India/SG connect expects E.164 with + for mobile legs."""
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 10:
        return f"+91{digits}"
    if digits.startswith("91") and len(digits) == 12:
        return f"+{digits}"
    if digits.startswith("0") and len(digits) == 11:
        return f"+91{digits[1:]}"
    if phone.startswith("+"):
        return phone
    return f"+{digits}"


def _exotel_caller_id_display(settings: Settings) -> str:
    return settings.exotel_caller_id.strip()


def _exotel_exophone_leg(settings: Settings) -> str:
    raw = settings.exotel_caller_id.strip()
    if raw.startswith("+"):
        return raw
    digits = "".join(c for c in raw if c.isdigit())
    if digits.startswith("0"):
        return f"+91{digits[1:]}"
    if len(digits) == 10:
        return f"+91{digits}"
    return f"+{digits}"


def place_outbound_connect(
    *,
    to_e164: str,
    voice_url: str,
    status_callback_url: str,
    custom_field: str,
    settings: Settings | None = None,
) -> str:
    """Start an Exotel outbound connect call. Returns Exotel CallSid.

    Exotel rings ``From`` first — for AI outbound we set From=customer, To=ExoPhone/SIP bridge.
    """
    s = settings or get_settings()
    if not exotel_configured(s):
        raise RuntimeError("Exotel is not configured")

    customer = _exotel_e164(to_e164)
    caller_id = _exotel_caller_id_display(s)
    exo_leg = _exotel_exophone_leg(s)
    root = _exotel_api_root(s)
    url = f"{root}/v1/Accounts/{s.exotel_account_sid}/Calls/connect.json"
    form = {
        "From": customer,
        "To": exo_leg,
        "CallerId": caller_id,
        "CallType": "trans",
        "Url": voice_url,
        "StatusCallback": status_callback_url,
        "StatusCallbackContentType": "application/json",
        "CustomField": custom_field[:128],
        "Record": "false",
        "TimeOut": "45",
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            url,
            data=form,
            headers={"Authorization": _auth_header(s)},
        )
    if response.status_code >= 400:
        logger.error("Exotel connect failed: %s %s", response.status_code, response.text)
        raise RuntimeError(f"Exotel connect failed: {response.status_code} {response.text[:500]}")
    payload = response.json()
    call_sid = (
        payload.get("Call", {}).get("Sid")
        or payload.get("CallSid")
        or payload.get("Sid")
    )
    if not call_sid:
        raise RuntimeError("Exotel response missing CallSid")
    return str(call_sid)


def fetch_call_details(call_sid: str, settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    root = _exotel_api_root(s)
    url = f"{root}/v1/Accounts/{s.exotel_account_sid}/Calls/{call_sid}.json"
    with httpx.Client(timeout=20.0) as client:
        response = client.get(url, headers={"Authorization": _auth_header(s)})
    response.raise_for_status()
    return response.json()