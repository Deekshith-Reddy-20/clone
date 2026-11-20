import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import Call

from app.services.calls import (
    apply_provider_status,
    dispatch_inbound_exotel_call,
    employee_snapshot_for_inbound,
    resolve_inbound_employee,
    sync_exotel_call,
)
from app.services.telephony.exotel import map_exotel_status
from app.services.telephony.inbound_mode import resolved_inbound_voice_mode
from app.services.telephony.livekit_svc import livekit_sip_dial_target, room_name_for_call
from app.services.voice.exotel_gemini_xml import exotel_gemini_open_xml, exotel_gemini_turn_xml
from app.services.voice.inbound_conversation import process_inbound_speech

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


def _xml_escape_text(text: str) -> str:
    return (
        text.replace("&", "and")
        .replace("<", " ")
        .replace(">", " ")
        .replace('"', "'")
    )


def _exotel_hold_xml(message: str, *, seconds: int = 90) -> str:
    say_line = _xml_escape_text(message)[:400]
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="woman">{say_line}</Say>
  <Pause length="{min(seconds, 300)}"/>
</Response>"""


def _exotel_voice_xml(
    call_id: str,
    *,
    room_name: str | None = None,
    greeting: str | None = None,
) -> str:
    settings = get_settings()
    room = room_name or room_name_for_call(call_id)
    say_line = _xml_escape_text(
        greeting or "Connecting you to your Karyuk agent. One moment please."
    )[:400]
    base = settings.public_api_base_url.rstrip("/")
    dial_action = f"{base}/v1/webhooks/exotel/inbound/dial-result/{call_id}"

    if settings.livekit_sip_uri.strip() and settings.inbound_dial_livekit:
        sip_uri = livekit_sip_dial_target(room)
        if not sip_uri:
            return _exotel_hold_xml(
                say_line + " Please hold while we connect you.",
                seconds=120,
            )
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="woman">{say_line}</Say>
  <Dial action="{dial_action}" method="POST" timeout="50" hangupOnStar="false" record="false">
    <Sip>{sip_uri}</Sip>
  </Dial>
</Response>"""

    if settings.livekit_sip_uri.strip() and not settings.inbound_dial_livekit:
        return _exotel_hold_xml(
            say_line + " Our team line is active. Please stay on the call.",
            seconds=180,
        )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="woman">Welcome to Karyuk. Your AI employee is joining now. Call reference {call_id[:8]}.</Say>
  <Pause length="30"/>
</Response>"""


def _exotel_error_xml(message: str) -> str:
    safe = message.replace("&", "and").replace("<", " ")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="woman">{safe}</Say>
  <Hangup/>
</Response>"""


async def _exotel_params(request: Request) -> dict[str, str]:
    if request.method == "POST":
        try:
            form = dict(await request.form())
            if form:
                return {str(k): str(v) for k, v in form.items()}
        except Exception:
            pass
    return {k: v for k, v in request.query_params.items()}


@router.api_route("/exotel/inbound", methods=["GET", "POST"])
async def exotel_inbound(
    request: Request,
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    """Exotel ExoPhone applet URL — caller dials your virtual number (no outbound KYC)."""
    params = await _exotel_params(request)
    caller = params.get("From") or params.get("CallFrom") or ""
    to_leg = params.get("To") or params.get("CallTo") or params.get("DialWhomNumber") or ""
    call_sid = params.get("CallSid") or params.get("Sid") or ""

    logger.info(
        "Exotel inbound From=%s To=%s CallSid=%s",
        caller[:24],
        to_leg[:24],
        call_sid[:32],
    )

    voice_mode = resolved_inbound_voice_mode()

    if call_sid:
        existing = db.scalars(select(Call).where(Call.provider_call_sid == call_sid)).first()
        if existing and existing.finalized_at is None:
            greet = "Thanks for calling Karyuk."
            if existing.employee_id:
                snap = employee_snapshot_for_inbound(db, existing.employee_id)
                brief = (snap.get("brief") or "").strip()
                if brief:
                    greet = f"Thanks for calling. {brief[:220]}"
            if voice_mode in ("exotel_gemini", "sarvam"):
                return PlainTextResponse(
                    exotel_gemini_open_xml(existing.id, greeting=greet),
                    media_type="application/xml",
                )
            room = existing.livekit_room or room_name_for_call(str(existing.id))
            return PlainTextResponse(
                _exotel_voice_xml(str(existing.id), room_name=room, greeting=greet),
                media_type="application/xml",
            )

    call = dispatch_inbound_exotel_call(
        db,
        caller_raw=caller,
        to_raw=to_leg,
        provider_call_sid=call_sid,
    )
    if not call:
        return PlainTextResponse(
            _exotel_error_xml(
                "No AI employee is assigned to this number. Register the ExoPhone in Karyuk Numbers and publish an employee."
            ),
            media_type="application/xml",
        )

    room = call.livekit_room or room_name_for_call(str(call.id))
    greet = None
    if call.employee_id:
        snap = employee_snapshot_for_inbound(db, call.employee_id)
        brief = (snap.get("brief") or "").strip()
        if brief:
            greet = f"Thanks for calling. {brief[:220]}"
    logger.info(
        "Exotel inbound new call %s employee=%s mode=%s room=%s",
        call.id,
        call.employee_id,
        voice_mode,
        room,
    )
    if voice_mode in ("exotel_gemini", "sarvam"):
        return PlainTextResponse(
            exotel_gemini_open_xml(call.id, greeting=greet or "Welcome to Karyuk."),
            media_type="application/xml",
        )
    return PlainTextResponse(
        _exotel_voice_xml(str(call.id), room_name=room, greeting=greet),
        media_type="application/xml",
    )


@router.api_route("/exotel/voicebot", methods=["GET", "POST", "HEAD"])
async def exotel_voicebot_resolve(
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Exotel Voicebot applet: return WSS URL for bidirectional AI (listen / speak)."""
    if request.method == "HEAD":
        return JSONResponse(content={}, status_code=200)
    params = await _exotel_params(request)
    caller = params.get("From") or params.get("CallFrom") or ""
    to_leg = params.get("To") or params.get("CallTo") or ""
    call_sid = params.get("CallSid") or params.get("Sid") or ""
    logger.info(
        "Exotel voicebot resolve From=%s To=%s CallSid=%s",
        (caller or "")[:24],
        (to_leg or "")[:24],
        (call_sid or "")[:32],
    )
    call = dispatch_inbound_exotel_call(
        db,
        caller_raw=caller,
        to_raw=to_leg,
        provider_call_sid=call_sid,
    )
    if not call:
        return JSONResponse(
            {
                "error": (
                    "Inbound not ready: register the ExoPhone in Karyuk Numbers, "
                    "publish an employee, and ensure workspace credits (dev auto top-up may need API restart)."
                )
            },
            status_code=404,
        )
    settings = get_settings()
    base = settings.public_api_base_url.rstrip("/")
    if base.startswith("https://"):
        wss = "wss://" + base.removeprefix("https://")
    elif base.startswith("http://"):
        wss = "ws://" + base.removeprefix("http://")
    else:
        wss = base
    return JSONResponse({"url": f"{wss}/v1/ws/exotel/voice/{call.id}"})


@router.api_route("/exotel/inbound/greeting", methods=["GET", "POST", "HEAD"])
async def exotel_inbound_greeting(
    request: Request,
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    """Exotel Greeting applet (URL): plain English text, not ExoML. Quick App Builder connectivity test."""
    if request.method == "HEAD":
        return PlainTextResponse("", media_type="text/plain")
    params = await _exotel_params(request)
    to_leg = params.get("To") or params.get("CallTo") or ""
    route = resolve_inbound_employee(db, to_raw=to_leg)
    if not route:
        return PlainTextResponse(
            "Welcome to Karyuk. This number is not registered yet.",
            media_type="text/plain",
        )
    _workspace_id, employee_id, _phone_id = route
    snap = employee_snapshot_for_inbound(db, employee_id)
    brief = (snap.get("brief") or "How can I help you today?").strip()
    return PlainTextResponse(
        f"Thanks for calling. {brief[:320]}",
        media_type="text/plain",
    )


@router.api_route("/exotel/inbound/conversation/{call_id}", methods=["GET", "POST"])
async def exotel_inbound_conversation(
    call_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    """Exotel Gather speech loop — Gemini (or rule-based) replies without LiveKit."""
    params = await _exotel_params(request)
    speech = (
        params.get("SpeechResult")
        or params.get("speech_result")
        or params.get("TranscriptionText")
        or ""
    )
    call = db.get(Call, call_id)
    if not call:
        return PlainTextResponse(_exotel_error_xml("Call session not found."), media_type="application/xml")

    reply, hangup = process_inbound_speech(db, call, caller_text=speech)
    return PlainTextResponse(
        exotel_gemini_turn_xml(call_id, agent_say=reply, hangup=hangup),
        media_type="application/xml",
    )


@router.api_route("/exotel/inbound/dial-result/{call_id}", methods=["GET", "POST"])
async def exotel_inbound_dial_result(
    call_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    """Exotel posts here after <Dial><Sip> — avoid instant hangup when LiveKit leg fails."""
    params = await _exotel_params(request)
    dial_status = (params.get("DialCallStatus") or params.get("Status") or "").lower()
    logger.warning(
        "Exotel dial result call=%s status=%s detail=%s",
        call_id,
        dial_status,
        {k: params[k] for k in list(params)[:12]},
    )
    call = db.get(Call, call_id)
    if call and dial_status in ("completed", "answered"):
        return PlainTextResponse(
            _exotel_hold_xml("Thank you for calling. Goodbye.", seconds=5),
            media_type="application/xml",
        )
    return PlainTextResponse(
        _exotel_hold_xml(
            "We are still connecting your AI agent. Please stay on the line.",
            seconds=90,
        ),
        media_type="application/xml",
    )


@router.api_route("/exotel/voice/{call_id}", methods=["GET", "POST"])
def exotel_voice(call_id: UUID, db: Session = Depends(get_db)) -> PlainTextResponse:
    call = db.get(Call, call_id)
    room = call.livekit_room if call else None
    return PlainTextResponse(
        _exotel_voice_xml(str(call_id), room_name=room),
        media_type="application/xml",
    )


@router.api_route("/exotel/status/{call_id}", methods=["GET", "POST"])
async def exotel_status(
    call_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    call = db.get(Call, call_id)
    if not call:
        logger.warning("Exotel status for unknown call %s", call_id)
        return {"ok": False}

    params = await _exotel_params(request)
    status = (
        params.get("Status")
        or params.get("CallStatus")
        or "queued"
    )
    duration = int(params.get("Duration") or 0)
    apply_provider_status(db, call, map_exotel_status(str(status)), duration_seconds=duration)
    return {"ok": True, "call_id": str(call_id), "status": status}


@router.post("/exotel/status/{call_id}/sync")
def exotel_manual_sync(call_id: UUID, db: Session = Depends(get_db)) -> dict:
    call = db.get(Call, call_id)
    if not call:
        return {"ok": False}
    sync_exotel_call(db, call)
    return {
        "ok": True,
        "call_id": str(call.id),
        "outcome": call.outcome.value if hasattr(call.outcome, "value") else call.outcome,
    }