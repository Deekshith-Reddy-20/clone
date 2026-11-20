import hashlib
import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Call, Employee, EmployeeVersion, Lead, PhoneNumber, WebhookDelivery, WebhookEndpoint
from app.models.enums import (
    CallDirection,
    CallOutcome,
    EmployeeStatus,
    LeadStatus,
    PhoneNumberStatus,
    WebhookDeliveryStatus,
)
from app.services.employees import get_draft
from app.services.telephony import telephony_mode
from app.services.telephony.exotel import exotel_configured, map_exotel_status, place_outbound_connect
from app.services.phone import e164_variants, normalize_e164
from app.services.telephony.inbound_mode import resolved_inbound_voice_mode
from app.services.telephony.livekit_svc import dispatch_voice_runtime, livekit_configured
from app.services.voice.voice_catalog import (
    DEFAULT_PREVIEW_SPEAKER,
    is_valid_preview_speaker,
    resolve_tts_speaker,
)
from app.services.wallet import reserve_for_call, settle_call

logger = logging.getLogger(__name__)

RESERVE_PAISE = 700
TARIFF_PAISE_PER_MIN = 700

TERMINAL_OUTCOMES = {
    CallOutcome.completed,
    CallOutcome.no_answer,
    CallOutcome.busy,
    CallOutcome.failed,
    CallOutcome.canceled,
}


def _lead_eligible(db: Session, lead: Lead) -> bool:
    return lead.status == LeadStatus.eligible


def employee_snapshot_for_inbound(db: Session, employee_id: UUID) -> dict:
    employee = db.get(Employee, employee_id)
    if not employee:
        return {}
    return _employee_snapshot(db, employee)


def _employee_draft_snapshot(db: Session, employee: Employee) -> dict:
    """Browser voice test — draft brief, knowledge, mode, speaker (not live publish pin)."""
    from app.services.employees import get_draft

    draft = get_draft(db, employee.id)
    published = _employee_snapshot(db, employee)
    if not draft:
        return {**published, "knowledge_state": "draft"}
    return {
        "brief": draft.brief,
        "language": draft.language,
        "natural_spoken": draft.natural_spoken,
        "mode": draft.mode.value if hasattr(draft.mode, "value") else str(draft.mode),
        "website_url": draft.website_url or "",
        "website_knowledge": draft.website_knowledge or "",
        "revision": draft.revision,
        "version_number": published.get("version_number"),
        "tts_speaker": resolve_tts_speaker(getattr(draft, "tts_speaker", None)),
        "knowledge_state": "draft",
    }


def _employee_snapshot(db: Session, employee: Employee) -> dict:
    if employee.active_version_id:
        version = db.get(EmployeeVersion, employee.active_version_id)
        if version:
            return dict(version.snapshot)
    draft = get_draft(db, employee.id)
    if draft:
        return {
            "brief": draft.brief,
            "language": draft.language,
            "natural_spoken": draft.natural_spoken,
            "mode": draft.mode.value if hasattr(draft.mode, "value") else str(draft.mode),
            "website_url": draft.website_url,
            "website_knowledge": draft.website_knowledge,
            "revision": draft.revision,
            "tts_speaker": resolve_tts_speaker(getattr(draft, "tts_speaker", None)),
        }
    return {"brief": "Karyuk agent", "language": "English"}


def _finalize_call(
    db: Session,
    *,
    workspace_id: UUID,
    call: Call,
    call_ref: str,
    duration: int,
    cost: int,
    transcript: str,
    summary: str,
    captured: dict | None = None,
) -> Call:
    call.duration_seconds = duration
    call.cost_paise = cost
    call.transcript = transcript
    call.summary = summary
    if captured:
        call.captured_fields = {**call.captured_fields, **captured}
    call.finalized_at = datetime.now(UTC)
    db.commit()
    db.refresh(call)
    settle_call(db, workspace_id, RESERVE_PAISE, cost, call_ref)
    _emit_call_webhooks(db, workspace_id, call)
    return call


def _complete_simulated(
    db: Session,
    *,
    workspace_id: UUID,
    call: Call,
    call_ref: str,
    lead: Lead | None,
    caller_e164: str | None = None,
) -> Call:
    call.provider = call.provider or "simulated"
    if lead:
        duration = 95
        transcript = (
            f"Caller ({lead.phone_e164}): Hi, I'm following up.\n"
            f"KARYUK: Thanks — recording your request per the employee brief.\n"
            f"Caller: Sounds good."
        )
        summary = "Simulated connected call (staging provider)."
        captured = {"intent": "follow_up", "confidence": "high"}
    else:
        duration = 60
        transcript = f"Inbound from {caller_e164}: Asked about availability. KARYUK: Shared configured fallback."
        summary = "Simulated inbound answered."
        captured = {"caller": caller_e164 or ""}

    call.direction = call.direction or CallDirection.outbound
    call.outcome = CallOutcome.completed
    return _finalize_call(
        db,
        workspace_id=workspace_id,
        call=call,
        call_ref=call_ref,
        duration=duration,
        cost=TARIFF_PAISE_PER_MIN,
        transcript=transcript,
        summary=summary,
        captured=captured,
    )


def dispatch_outbound_call(
    db: Session,
    *,
    workspace_id: UUID,
    employee_id: UUID,
    lead_id: UUID,
    campaign_id: UUID | None = None,
) -> Call:
    employee = db.execute(
        select(Employee).where(Employee.id == employee_id, Employee.workspace_id == workspace_id)
    ).scalar_one_or_none()
    if not employee or employee.status != EmployeeStatus.published:
        raise ValueError("Employee must be published")

    lead = db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.workspace_id == workspace_id)
    ).scalar_one_or_none()
    if not lead or not _lead_eligible(db, lead):
        raise ValueError("Lead not eligible")

    call_ref = str(uuid4())
    reserve_for_call(db, workspace_id, RESERVE_PAISE, call_ref)

    snapshot = _employee_snapshot(db, employee)
    call = Call(
        workspace_id=workspace_id,
        employee_id=employee_id,
        lead_id=lead_id,
        campaign_id=campaign_id,
        direction=CallDirection.outbound,
        outcome=CallOutcome.queued,
        captured_fields={"wallet_ref": call_ref},
    )
    db.add(call)
    db.flush()

    if livekit_configured():
        lk_meta = dispatch_voice_runtime(str(call.id), snapshot)
        call.livekit_room = lk_meta.get("room")
        call.captured_fields = {**call.captured_fields, "livekit": lk_meta}

    settings = get_settings()

    # Prefer Outpero voice agent when configured — bypasses Exotel KYC for outbound tests.
    if settings.outpero_prefer_outbound:
        outpero_call = _try_dispatch_outpero(
            db,
            workspace_id=workspace_id,
            call=call,
            lead=lead,
            call_ref=call_ref,
            snapshot=snapshot,
        )
        if outpero_call is not None:
            return outpero_call

    mode = telephony_mode(settings)
    if mode == "exotel" and exotel_configured(settings):
        base = settings.public_api_base_url.rstrip("/")
        voice_url = f"{base}/v1/webhooks/exotel/voice/{call.id}"
        status_url = f"{base}/v1/webhooks/exotel/status/{call.id}"
        try:
            sid = place_outbound_connect(
                to_e164=lead.phone_e164,
                voice_url=voice_url,
                status_callback_url=status_url,
                custom_field=str(call.id),
                settings=settings,
            )
            call.provider = "exotel"
            call.provider_call_sid = sid
            call.outcome = CallOutcome.dialing
            db.commit()
            db.refresh(call)
            return call
        except Exception as exc:
            logger.warning("Exotel dispatch failed: %s", exc)
            err = str(exc)
            call.captured_fields = {
                **call.captured_fields,
                "exotel_error": err[:500],
            }
            # If Exotel KYC blocks, automatically fall back to Outpero when available.
            if "KYC" in err.upper() or "403" in err:
                outpero_call = _try_dispatch_outpero(
                    db,
                    workspace_id=workspace_id,
                    call=call,
                    lead=lead,
                    call_ref=call_ref,
                    snapshot=snapshot,
                    force=True,
                )
                if outpero_call is not None:
                    return outpero_call
                call.provider = "exotel"
                call.outcome = CallOutcome.failed
                call.summary = (
                    "Phone provider blocked outbound (KYC). Connect a voice agent under "
                    "Calling → Voice agents, or dial your inbound number to test."
                )
                call.transcript = err[:1000]
            else:
                call.provider = "exotel"
                call.outcome = CallOutcome.failed
                call.summary = "Outbound phone call failed."
                call.transcript = err[:1000]
            call.finalized_at = datetime.now(UTC)
            db.commit()
            from app.services.wallet import release_reserve

            release_reserve(db, workspace_id, RESERVE_PAISE, call_ref)
            db.refresh(call)
            return call

    return _complete_simulated(
        db,
        workspace_id=workspace_id,
        call=call,
        call_ref=call_ref,
        lead=lead,
    )


def _try_dispatch_outpero(
    db: Session,
    *,
    workspace_id: UUID,
    call: Call,
    lead: Lead,
    call_ref: str,
    snapshot: dict,
    force: bool = False,
) -> Call | None:
    from app.services.outpero.agents import ensure_env_agent, get_active_agent
    from app.services.outpero.client import OutperoApiError, OutperoClient

    ensure_env_agent(db, workspace_id)
    agent = get_active_agent(db, workspace_id)
    if not agent:
        return None

    pre_call: dict = {
        "lead_name": lead.name or "",
        "karyuk_employee_brief": (snapshot.get("brief") or "")[:400],
        "karyuk_language": snapshot.get("language") or "English",
    }
    if force:
        pre_call["karyuk_exotel_fallback"] = True

    client = OutperoClient()
    try:
        response = client.submit_lead(
            slug=agent.slug,
            lead_secret=agent.lead_secret,
            phone=lead.phone_e164,
            pre_call={k: v for k, v in pre_call.items() if v},
        )
    except OutperoApiError as exc:
        logger.warning("Outpero outbound failed: %s", exc)
        call.captured_fields = {
            **(call.captured_fields or {}),
            "outpero_error": str(exc)[:500],
            "wallet_ref": call_ref,
        }
        if force:
            return None
        call.provider = "outpero"
        call.outpero_agent_id = agent.id
        call.outcome = CallOutcome.failed
        call.summary = f"Voice agent call failed: {exc}"
        call.transcript = str(exc)[:1000]
        call.finalized_at = datetime.now(UTC)
        db.commit()
        from app.services.wallet import release_reserve

        release_reserve(db, workspace_id, RESERVE_PAISE, call_ref)
        db.refresh(call)
        return call

    external_call_id = None
    for key in ("call_id", "id", "callId"):
        if response.get(key):
            external_call_id = str(response[key])
            break
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    if not external_call_id:
        for key in ("call_id", "id"):
            if data.get(key):
                external_call_id = str(data[key])
                break

    call.provider = "outpero"
    call.outpero_agent_id = agent.id
    call.provider_call_sid = external_call_id
    call.outcome = CallOutcome.queued
    call.started_at = datetime.now(UTC)
    call.captured_fields = {
        **(call.captured_fields or {}),
        "wallet_ref": call_ref,
        "pre_call": pre_call,
        "outpero_submit_response": {
            k: v for k, v in response.items() if k not in {"transcript", "recording_url"}
        },
        "exotel_error": None,
    }
    agent.last_activity_at = datetime.now(UTC)
    db.commit()
    db.refresh(call)
    logger.info(
        "Outpero outbound queued call_id=%s external=%s agent=%s",
        call.id,
        external_call_id,
        agent.slug,
    )
    return call


def sync_exotel_call(db: Session, call: Call) -> Call:
    if call.provider != "exotel" or not call.provider_call_sid:
        return call
    from app.services.telephony.exotel import fetch_call_details

    try:
        payload = fetch_call_details(call.provider_call_sid)
    except Exception as exc:
        logger.warning("Exotel sync failed for %s: %s", call.id, exc)
        return call
    call_data = payload.get("Call", payload)
    status = call_data.get("Status") or call_data.get("status") or "queued"
    duration = int(call_data.get("Duration") or call_data.get("duration") or 0)
    apply_provider_status(db, call, map_exotel_status(str(status)), duration_seconds=duration)
    return call


def apply_provider_status(
    db: Session,
    call: Call,
    outcome_key: str,
    *,
    duration_seconds: int = 0,
) -> Call:
    try:
        outcome = CallOutcome(outcome_key)
    except ValueError:
        outcome = CallOutcome.queued
    call.outcome = outcome
    workspace_id = call.workspace_id
    call_ref = call.captured_fields.get("wallet_ref", str(call.id))

    from app.services.voice.call_finalize import finalize_call_idempotent

    was_open = not call.finalized_at
    call = finalize_call_idempotent(
        db,
        call,
        duration_seconds=duration_seconds,
        outcome=outcome,
        source="exotel_status_callback",
    )
    if was_open and call.finalized_at and outcome in TERMINAL_OUTCOMES:
        if outcome == CallOutcome.completed:
            if not call.captured_fields.get("wallet_settled"):
                cost = max(TARIFF_PAISE_PER_MIN, (duration_seconds // 60 + 1) * TARIFF_PAISE_PER_MIN)
                transcript = call.transcript or "Call completed (provider)."
                summary = call.summary or "Exotel call finished."
                _finalize_call(
                    db,
                    workspace_id=workspace_id,
                    call=call,
                    call_ref=call_ref,
                    duration=call.duration_seconds or duration_seconds or 1,
                    cost=cost,
                    transcript=transcript,
                    summary=summary,
                    captured={"wallet_settled": True},
                )
        else:
            call.cost_paise = call.cost_paise or 0
            call.captured_fields = {**call.captured_fields, "wallet_settled": True}
            db.commit()
            from app.services.wallet import release_reserve

            release_reserve(db, workspace_id, RESERVE_PAISE, call_ref)
    elif not was_open and outcome in TERMINAL_OUTCOMES and not call.captured_fields.get("wallet_settled"):
        if outcome == CallOutcome.completed:
            cost = max(TARIFF_PAISE_PER_MIN, ((call.duration_seconds or duration_seconds) // 60 + 1) * TARIFF_PAISE_PER_MIN)
            _finalize_call(
                db,
                workspace_id=workspace_id,
                call=call,
                call_ref=call_ref,
                duration=call.duration_seconds or duration_seconds or 1,
                cost=cost,
                transcript=call.transcript or "Call completed (provider).",
                summary=call.summary or "Exotel call finished.",
                captured={"wallet_settled": True},
            )
        else:
            call.captured_fields = {**call.captured_fields, "wallet_settled": True}
            db.commit()
            from app.services.wallet import release_reserve

            release_reserve(db, workspace_id, RESERVE_PAISE, call_ref)
    db.refresh(call)
    return call


def simulate_outbound_call(
    db: Session,
    *,
    workspace_id: UUID,
    employee_id: UUID,
    lead_id: UUID,
    campaign_id: UUID | None = None,
) -> Call:
    return dispatch_outbound_call(
        db,
        workspace_id=workspace_id,
        employee_id=employee_id,
        lead_id=lead_id,
        campaign_id=campaign_id,
    )


def resolve_inbound_employee(
    db: Session,
    *,
    to_raw: str,
    settings=None,
) -> tuple[UUID, UUID, UUID | None] | None:
    """Return workspace_id, employee_id, optional phone_number_id for an inbound To leg."""
    from app.config import get_settings

    s = settings or get_settings()
    variants = e164_variants(to_raw or s.exotel_caller_id)
    variants |= e164_variants(s.exotel_caller_id)

    # Newest registration wins when the same ExoPhone exists in multiple workspaces (e.g. old test setups).
    rows = db.scalars(
        select(PhoneNumber)
        .where(
            PhoneNumber.inbound_enabled.is_(True),
            PhoneNumber.status == PhoneNumberStatus.active,
        )
        .order_by(PhoneNumber.created_at.desc())
    ).all()
    for row in rows:
        if not (e164_variants(row.e164) & variants):
            continue
        if row.employee_id:
            emp = db.get(Employee, row.employee_id)
            if emp and emp.status == EmployeeStatus.published:
                return row.workspace_id, row.employee_id, row.id
        emp = db.execute(
            select(Employee)
            .where(
                Employee.workspace_id == row.workspace_id,
                Employee.status == EmployeeStatus.published,
            )
            .order_by(Employee.created_at.desc())
        ).scalars().first()
        if emp:
            return row.workspace_id, emp.id, row.id

    ws_raw = s.exotel_inbound_fallback_workspace_id.strip()
    emp_raw = s.exotel_inbound_fallback_employee_id.strip()
    if ws_raw and emp_raw:
        try:
            return UUID(ws_raw), UUID(emp_raw), None
        except ValueError:
            pass
    return None


def dispatch_inbound_exotel_call(
    db: Session,
    *,
    caller_raw: str,
    to_raw: str,
    provider_call_sid: str,
) -> Call | None:
    settings = get_settings()
    route = resolve_inbound_employee(db, to_raw=to_raw, settings=settings)
    if not route:
        return None
    workspace_id, employee_id, phone_number_id = route

    try:
        caller_e164 = normalize_e164(caller_raw)
    except ValueError:
        caller_e164 = caller_raw or "unknown"

    employee = db.get(Employee, employee_id)
    if not employee or employee.status != EmployeeStatus.published:
        return None

    if provider_call_sid:
        existing = db.scalars(
            select(Call).where(Call.provider_call_sid == provider_call_sid)
        ).first()
        if existing and existing.finalized_at is None:
            return existing

    call_ref = str(uuid4())
    try:
        reserve_for_call(db, workspace_id, RESERVE_PAISE, call_ref)
    except ValueError:
        logger.warning("Inbound call blocked: insufficient credits for workspace %s", workspace_id)
        return None
    snapshot = _employee_snapshot(db, employee)
    from app.services.employee_knowledge import supplemental_for_inbound

    supplemental, _web_part, _ws_part = supplemental_for_inbound(
        snapshot, db, workspace_id, prefer_frozen_workspace=False
    )
    call = Call(
        workspace_id=workspace_id,
        employee_id=employee_id,
        phone_number_id=phone_number_id,
        direction=CallDirection.inbound,
        outcome=CallOutcome.connected,
        provider="exotel",
        provider_call_sid=provider_call_sid[:128] if provider_call_sid else None,
        captured_fields={
            "wallet_ref": call_ref,
            "caller_e164": caller_e164,
            "inbound_to": to_raw,
        },
    )
    db.add(call)
    db.flush()

    from app.services.telephony.inbound_mode import resolved_inbound_voice_mode

    if resolved_inbound_voice_mode(settings) == "livekit" and livekit_configured():
        lk_meta = dispatch_voice_runtime(str(call.id), snapshot)
        call.livekit_room = lk_meta.get("room")
        call.captured_fields = {**call.captured_fields, "livekit": lk_meta}
    else:
        knowledge_state = "published" if employee.active_version_id else "draft"
        from app.services.voice.sarvam import SARVAM_SPEECH_STACK

        call.captured_fields = {
            **call.captured_fields,
            "inbound_voice_mode": resolved_inbound_voice_mode(settings),
            "sarvam_speech_stack": SARVAM_SPEECH_STACK,
            "employee_brief": snapshot.get("brief", ""),
            "employee_language": snapshot.get("language", "English"),
            "employee_natural_spoken": bool(snapshot.get("natural_spoken", True)),
            "employee_mode": snapshot.get("mode") or "",
            "employee_website_url": snapshot.get("website_url") or "",
            "employee_website_knowledge": supplemental,
            "employee_workspace_knowledge": _ws_part,
            "employee_snapshot_revision": str(snapshot.get("revision") or ""),
            "employee_version_number": str(snapshot.get("version_number") or ""),
            "knowledge_state": knowledge_state,
            "knowledge_source_url": str(snapshot.get("website_url") or ""),
            "knowledge_fetched_at": str(snapshot.get("website_fetched_at") or ""),
            "knowledge_content_version": hashlib.sha256(supplemental.encode()).hexdigest()[:12],
            "tts_speaker": resolve_tts_speaker(str(snapshot.get("tts_speaker") or "")),
            "inbound_chat": {"turns": []},
        }

    from app.services.employee_knowledge import pin_call_voice_grounding

    pin_call_voice_grounding(db, call)
    db.commit()
    db.refresh(call)
    return call


def create_browser_voice_preview_call(
    db: Session,
    *,
    workspace_id: UUID,
    employee_id: UUID,
    tts_speaker: str,
) -> Call:
    """In-browser call test — same Sarvam stack as Exotel, no PSTN."""
    settings = get_settings()
    employee = db.get(Employee, employee_id)
    if not employee or employee.workspace_id != workspace_id:
        raise ValueError("Employee not found")
    published_snap = _employee_snapshot(db, employee)
    snapshot = _employee_draft_snapshot(db, employee)
    from app.services.employee_knowledge import (
        combine_supplemental_knowledge,
        workspace_knowledge_text,
    )

    ws_live = workspace_knowledge_text(db, workspace_id)
    draft_supplemental = combine_supplemental_knowledge(
        str(snapshot.get("website_knowledge") or ""),
        ws_live,
    )
    published = resolve_tts_speaker(str(published_snap.get("tts_speaker") or ""))
    speaker = (
        tts_speaker.strip().lower()
        if is_valid_preview_speaker(tts_speaker)
        else resolve_tts_speaker(str(snapshot.get("tts_speaker") or "")) or published
    )
    call_ref = str(uuid4())
    reserve_for_call(db, workspace_id, RESERVE_PAISE, call_ref)
    call = Call(
        workspace_id=workspace_id,
        employee_id=employee_id,
        direction=CallDirection.inbound,
        outcome=CallOutcome.connected,
        provider="browser_preview",
        captured_fields={
            "wallet_ref": call_ref,
            "caller_e164": "browser-preview",
            "inbound_voice_mode": resolved_inbound_voice_mode(settings),
            "employee_brief": snapshot.get("brief", ""),
            "employee_language": snapshot.get("language", "English"),
            "employee_natural_spoken": bool(snapshot.get("natural_spoken", True)),
            "employee_mode": snapshot.get("mode") or "",
            "employee_website_url": snapshot.get("website_url") or "",
            "employee_website_knowledge": draft_supplemental,
            "employee_workspace_knowledge": ws_live,
            "employee_snapshot_revision": str(snapshot.get("revision") or ""),
            "employee_version_number": str(snapshot.get("version_number") or ""),
            "knowledge_state": "draft",
            "published_snapshot_revision": str(published_snap.get("revision") or ""),
            "published_tts_speaker": published,
            "inbound_chat": {"turns": []},
            "browser_preview": True,
            "tts_speaker": speaker,
        },
    )
    from app.services.voice.sarvam import SARVAM_SPEECH_STACK

    call.captured_fields = {**(call.captured_fields or {}), "sarvam_speech_stack": SARVAM_SPEECH_STACK}
    db.add(call)
    db.commit()
    db.refresh(call)
    return call


SYNTHETIC_REPLAY_KNOWLEDGE = (
    "Swimming pool opens daily at 8:30 AM. Closes at 10 PM. No spa details listed."
)


def create_inbound_voice_replay_call(
    db: Session,
    *,
    caller_raw: str,
    to_raw: str,
    provider_call_sid: str,
    synthetic_knowledge: str | None = SYNTHETIC_REPLAY_KNOWLEDGE,
    browser_preview: bool = True,
) -> Call | None:
    """
    Same employee pin as Exotel dispatch, plus browser_preview for WS transcripts/STT.
    Optional synthetic knowledge is stored only on this Call row (not the live employee).
    """
    call = dispatch_inbound_exotel_call(
        db,
        caller_raw=caller_raw,
        to_raw=to_raw,
        provider_call_sid=provider_call_sid,
    )
    if not call:
        return None
    fields = dict(call.captured_fields or {})
    know = (fields.get("employee_website_knowledge") or "").strip()
    if synthetic_knowledge and len(know) < 12:
        fields["employee_website_knowledge"] = synthetic_knowledge.strip()
    fields["browser_preview"] = browser_preview
    fields["voice_replay"] = True
    call.captured_fields = fields
    db.commit()
    db.refresh(call)
    return call


def simulate_inbound_call(
    db: Session,
    *,
    workspace_id: UUID,
    employee_id: UUID,
    caller_e164: str,
) -> Call:
    call_ref = str(uuid4())
    reserve_for_call(db, workspace_id, RESERVE_PAISE, call_ref)
    call = Call(
        workspace_id=workspace_id,
        employee_id=employee_id,
        direction=CallDirection.inbound,
        outcome=CallOutcome.queued,
        captured_fields={"wallet_ref": call_ref},
    )
    db.add(call)
    db.flush()
    return _complete_simulated(
        db,
        workspace_id=workspace_id,
        call=call,
        call_ref=call_ref,
        lead=None,
        caller_e164=caller_e164,
    )


def _emit_call_webhooks(db: Session, workspace_id: UUID, call: Call) -> None:
    endpoints = db.scalars(
        select(WebhookEndpoint).where(
            WebhookEndpoint.workspace_id == workspace_id,
        )
    ).all()
    event_id = f"evt_{call.id}"
    payload = {
        "event_id": event_id,
        "event_type": "call.finalized.v1",
        "call_id": str(call.id),
        "outcome": call.outcome.value if hasattr(call.outcome, "value") else call.outcome,
        "duration_seconds": call.duration_seconds,
    }
    for endpoint in endpoints:
        delivery = WebhookDelivery(
            workspace_id=workspace_id,
            endpoint_id=endpoint.id,
            event_id=str(uuid4()),
            event_type="call.finalized.v1",
            payload=payload,
            status=WebhookDeliveryStatus.delivered,
            response_code=200,
        )
        db.add(delivery)
    db.commit()