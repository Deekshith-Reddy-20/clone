import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)
from sqlalchemy.orm import Session

from app.auth.deps import get_workspace_membership
from app.database import get_db
from app.models import Membership
from sqlalchemy import select

from app.models import PhoneNumber
from app.models.enums import CallMode, EmployeeStatus
from app.schemas.employee import (
    EmployeeCreate,
    EmployeeDraftOut,
    EmployeeDraftUpdate,
    EmployeeInboundReadinessOut,
    EmployeeOut,
    EmployeePublishedSnapshotOut,
    EmployeeVersionOut,
    VoicePreviewCreate,
    VoicePreviewSessionOut,
    VoicePreviewVoiceOut,
    WebsiteAnalyzeRequest,
    WebsiteAnalyzeResponse,
)
from app.services.calls import _employee_snapshot, create_browser_voice_preview_call
from app.services.employee_knowledge import knowledge_metrics
from app.services.voice.voice_catalog import resolve_tts_speaker
from app.services.employee_readiness import employee_go_live_readiness
from app.services.employees import (
    analyze_employee_website,
    create_employee,
    get_draft,
    get_employee,
    list_employees,
    publish_employee,
    update_draft,
)

router = APIRouter(prefix="/v1/workspaces/{workspace_id}", tags=["employees"])


def _draft_out(draft) -> EmployeeDraftOut:
    from app.schemas.business_profile import BusinessProfile

    profile = draft.business_profile if isinstance(getattr(draft, "business_profile", None), dict) else None
    warnings = BusinessProfile.from_snapshot(profile).warnings() if profile else []
    return EmployeeDraftOut(
        revision=draft.revision,
        brief=draft.brief,
        operator_instructions=getattr(draft, "operator_instructions", "") or "",
        business_profile=profile,
        persona=getattr(draft, "persona", None),
        profile_warnings=warnings,
        language=draft.language,
        natural_spoken=draft.natural_spoken,
        mode=draft.mode,
        tts_speaker=getattr(draft, "tts_speaker", None) or "shubh",
        website_url=draft.website_url,
        website_knowledge=draft.website_knowledge,
        updated_at=draft.updated_at,
    )


def _employee_out(db: Session, employee) -> EmployeeOut:
    draft = get_draft(db, employee.id)
    draft_out = _draft_out(draft) if draft else None
    published_out = None
    if employee.active_version_id:
        snap = _employee_snapshot(db, employee)
        metrics = knowledge_metrics(
            brief=str(snap.get("brief") or ""),
            website_knowledge=str(snap.get("website_knowledge") or ""),
            workspace_knowledge=str(snap.get("workspace_knowledge") or ""),
        )
        published_out = EmployeePublishedSnapshotOut(
            version_number=int(snap.get("version_number") or 0),
            snapshot_revision=int(snap.get("revision") or 0),
            brief=str(snap.get("brief") or ""),
            language=str(snap.get("language") or "English"),
            natural_spoken=bool(snap.get("natural_spoken", True)),
            mode=CallMode(str(snap.get("mode") or CallMode.instant.value)),
            tts_speaker=resolve_tts_speaker(str(snap.get("tts_speaker") or "")),
            website_url=snap.get("website_url"),
            knowledge_chars=metrics["total_grounding_chars"],
            brief_chars=metrics["brief_chars"],
            website_knowledge_chars=metrics["website_chars"],
            workspace_knowledge_chars=metrics["workspace_chars"],
        )
    phones = list(
        db.scalars(
            select(PhoneNumber).where(
                PhoneNumber.employee_id == employee.id,
                PhoneNumber.inbound_enabled.is_(True),
            )
        ).all()
    )
    is_published = employee.status == EmployeeStatus.published
    inbound_out = EmployeeInboundReadinessOut(
        published=is_published,
        assigned_numbers=[p.e164 for p in phones],
        can_receive_inbound=is_published and len(phones) > 0,
    )
    return EmployeeOut(
        id=employee.id,
        workspace_id=employee.workspace_id,
        status=employee.status.value if hasattr(employee.status, "value") else str(employee.status),
        active_version_id=employee.active_version_id,
        draft=draft_out,
        published_snapshot=published_out,
        inbound_readiness=inbound_out,
        created_at=employee.created_at,
    )


@router.get("/employees", response_model=list[EmployeeOut])
def list_workspace_employees(
    workspace_id: UUID,
    _membership: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
) -> list[EmployeeOut]:
    return [_employee_out(db, e) for e in list_employees(db, workspace_id)]


@router.post("/employees", response_model=EmployeeOut, status_code=201)
def create_workspace_employee(
    workspace_id: UUID,
    body: EmployeeCreate,
    _membership: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
) -> EmployeeOut:
    employee = create_employee(db, workspace_id, body)
    return _employee_out(db, employee)


@router.get("/employees/{employee_id}/readiness")
def employee_readiness(
    workspace_id: UUID,
    employee_id: UUID,
    _membership: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
) -> dict:
    if not get_employee(db, workspace_id, employee_id):
        raise HTTPException(status_code=404, detail="Employee not found")
    try:
        return employee_go_live_readiness(db, workspace_id, employee_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/employees/{employee_id}", response_model=EmployeeOut)
def get_workspace_employee(
    workspace_id: UUID,
    employee_id: UUID,
    _membership: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
) -> EmployeeOut:
    employee = get_employee(db, workspace_id, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    return _employee_out(db, employee)


@router.patch("/employees/{employee_id}/draft", response_model=EmployeeDraftOut)
def patch_employee_draft(
    workspace_id: UUID,
    employee_id: UUID,
    body: EmployeeDraftUpdate,
    _membership: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
) -> EmployeeDraftOut:
    if not get_employee(db, workspace_id, employee_id):
        raise HTTPException(status_code=404, detail="Employee not found")
    try:
        draft = update_draft(
            db, workspace_id=workspace_id, employee_id=employee_id, body=body
        )
    except ValueError as exc:
        if "Revision" in str(exc):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _draft_out(draft)


@router.post(
    "/employees/{employee_id}/website/analyze",
    response_model=WebsiteAnalyzeResponse,
)
def analyze_employee_website_route(
    workspace_id: UUID,
    employee_id: UUID,
    body: WebsiteAnalyzeRequest,
    _membership: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
) -> WebsiteAnalyzeResponse:
    if not get_employee(db, workspace_id, employee_id):
        raise HTTPException(status_code=404, detail="Employee not found")
    try:
        draft = analyze_employee_website(db, workspace_id, employee_id, body.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("Website analyze failed: %s", exc)
        raise HTTPException(status_code=502, detail="Could not fetch or analyze website") from exc
    knowledge = draft.website_knowledge or ""
    return WebsiteAnalyzeResponse(
        website_url=draft.website_url or body.url,
        website_knowledge=knowledge,
        revision=draft.revision,
    )


@router.get("/voice-preview/voices", response_model=list[VoicePreviewVoiceOut])
def list_voice_preview_voices(
    workspace_id: UUID,
    _membership: Membership = Depends(get_workspace_membership),
) -> list[VoicePreviewVoiceOut]:
    from app.services.voice.voice_catalog import PREVIEW_VOICES

    return [VoicePreviewVoiceOut(**v) for v in PREVIEW_VOICES]


@router.post(
    "/employees/{employee_id}/voice-preview",
    response_model=VoicePreviewSessionOut,
    status_code=201,
)
def start_voice_preview_session(
    workspace_id: UUID,
    employee_id: UUID,
    body: VoicePreviewCreate,
    _membership: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
) -> VoicePreviewSessionOut:
    employee = get_employee(db, workspace_id, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    published_speaker = resolve_tts_speaker(
        str(_employee_snapshot(db, employee).get("tts_speaker") or "")
    )
    try:
        call = create_browser_voice_preview_call(
            db,
            workspace_id=workspace_id,
            employee_id=employee_id,
            tts_speaker=body.speaker,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fields = call.captured_fields or {}
    speaker = str(fields.get("tts_speaker") or body.speaker)
    path = f"/v1/ws/exotel/voice/{call.id}"
    from app.services.voice.session_trace import _build_sha

    metrics = knowledge_metrics(
        brief=str(fields.get("employee_brief") or ""),
        website_knowledge=str(fields.get("employee_website_knowledge") or ""),
        workspace_knowledge=str(fields.get("employee_workspace_knowledge") or ""),
    )
    from app.services.voice.sarvam import sarvam_media_ready

    sarvam_ok, sarvam_reason = sarvam_media_ready(probe=True)
    sarvam_status = ""
    if not sarvam_ok:
        sarvam_status = (
            "Sarvam API has no credits — speech will not work until you top up. "
            "Infrastructure (WebSocket, routing) is still connected."
            if sarvam_reason == "insufficient_quota"
            else f"Sarvam not ready: {sarvam_reason}"
        )
    return VoicePreviewSessionOut(
        call_id=call.id,
        speaker=speaker,
        websocket_path=path,
        worker_build_sha=_build_sha(),
        employee_snapshot_revision=str(fields.get("employee_snapshot_revision") or ""),
        employee_version_number=str(fields.get("employee_version_number") or ""),
        speech_stack=str(fields.get("sarvam_speech_stack") or fields.get("inbound_voice_mode") or "sarvam"),
        knowledge_state=str(fields.get("knowledge_state") or "published"),
        published_speaker=published_speaker,
        published_mode=str(fields.get("employee_mode") or ""),
        knowledge_chars=metrics["total_grounding_chars"],
        sarvam_ready=sarvam_ok,
        sarvam_status=sarvam_status,
    )


@router.post("/employees/{employee_id}/publish", response_model=EmployeeVersionOut, status_code=201)
def publish_workspace_employee(
    workspace_id: UUID,
    employee_id: UUID,
    _membership: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
) -> EmployeeVersionOut:
    try:
        version = publish_employee(db, workspace_id, employee_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return EmployeeVersionOut(
        id=version.id,
        version_number=version.version_number,
        snapshot=version.snapshot,
        published_at=version.published_at,
    )