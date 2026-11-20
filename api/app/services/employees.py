import logging
from datetime import UTC, datetime
from uuid import UUID

logger = logging.getLogger(__name__)

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Employee, EmployeeDraft, EmployeeVersion
from app.models.enums import CallMode, EmployeeStatus
from app.schemas.employee import EmployeeCreate, EmployeeDraftUpdate
from app.services.voice.voice_catalog import resolve_tts_speaker
from app.services.employee_knowledge import workspace_knowledge_text
from app.services.website_knowledge import analyze_website, noted_website_fetch


def create_employee(db: Session, workspace_id: UUID, body: EmployeeCreate) -> Employee:
    employee = Employee(workspace_id=workspace_id, status=EmployeeStatus.draft)
    db.add(employee)
    db.flush()
    draft = EmployeeDraft(
        employee_id=employee.id,
        workspace_id=workspace_id,
        brief=body.brief.strip(),
        language=body.language,
        natural_spoken=body.natural_spoken,
        mode=body.mode,
        tts_speaker=resolve_tts_speaker(body.tts_speaker),
    )
    db.add(draft)
    db.commit()
    db.refresh(employee)
    db.refresh(draft)
    return employee


def list_employees(db: Session, workspace_id: UUID) -> list[Employee]:
    return list(
        db.scalars(
            select(Employee)
            .where(Employee.workspace_id == workspace_id)
            .order_by(Employee.created_at.desc())
        ).all()
    )


def get_employee(db: Session, workspace_id: UUID, employee_id: UUID) -> Employee | None:
    return db.execute(
        select(Employee).where(
            Employee.id == employee_id,
            Employee.workspace_id == workspace_id,
        )
    ).scalar_one_or_none()


def get_draft(db: Session, employee_id: UUID) -> EmployeeDraft | None:
    return db.execute(
        select(EmployeeDraft).where(EmployeeDraft.employee_id == employee_id)
    ).scalar_one_or_none()


def update_draft(
    db: Session,
    *,
    workspace_id: UUID,
    employee_id: UUID,
    body: EmployeeDraftUpdate,
) -> EmployeeDraft:
    draft = get_draft(db, employee_id)
    if not draft or draft.workspace_id != workspace_id:
        raise ValueError("Draft not found")
    if body.revision is not None and body.revision != draft.revision:
        raise ValueError("Revision conflict")

    if body.brief is not None:
        draft.brief = body.brief.strip()
    if body.language is not None:
        draft.language = body.language
    if body.natural_spoken is not None:
        draft.natural_spoken = body.natural_spoken
    if body.mode is not None:
        draft.mode = body.mode
    if body.tts_speaker is not None:
        draft.tts_speaker = resolve_tts_speaker(body.tts_speaker)
    if body.website_url is not None:
        url = body.website_url.strip() or None
        draft.website_url = url
    if body.website_knowledge is not None:
        draft.website_knowledge = body.website_knowledge.strip() or None
    if body.operator_instructions is not None:
        draft.operator_instructions = body.operator_instructions.strip()
    if body.business_profile is not None:
        draft.business_profile = body.business_profile
    if body.persona is not None:
        draft.persona = body.persona
    draft.revision += 1
    db.commit()
    db.refresh(draft)
    return draft


def analyze_employee_website(
    db: Session, workspace_id: UUID, employee_id: UUID, url: str
) -> EmployeeDraft:
    draft = get_draft(db, employee_id)
    if not draft or draft.workspace_id != workspace_id:
        raise ValueError("Draft not found")
    from app.services.business_profile_render import render_profile_facts
    from app.services.profile_extract import crawl_and_extract_profile, merge_profile_into_draft_fields

    normalized, knowledge = analyze_website(url)
    try:
        profile, crawl_text = crawl_and_extract_profile(normalized)
        op_inst, _brief, persona, profile_dict = merge_profile_into_draft_fields(
            brief=draft.brief,
            profile=profile,
            crawl_summary=crawl_text or knowledge,
        )
        draft.operator_instructions = op_inst or draft.operator_instructions or ""
        draft.persona = persona
        draft.business_profile = profile_dict
        rendered = render_profile_facts(profile)
        if rendered:
            knowledge = rendered
    except Exception:
        logger.exception("Profile crawl failed for %s — keeping page summary", url)
    draft.website_url = normalized
    draft.website_knowledge = knowledge
    draft.revision += 1
    db.commit()
    db.refresh(draft)
    return draft


def publish_employee(db: Session, workspace_id: UUID, employee_id: UUID) -> EmployeeVersion:
    employee = get_employee(db, workspace_id, employee_id)
    if not employee:
        raise ValueError("Employee not found")
    draft = get_draft(db, employee_id)
    if not draft or len(draft.brief.strip()) < 12:
        raise ValueError("Draft incomplete")

    last_version = db.execute(
        select(EmployeeVersion.version_number)
        .where(EmployeeVersion.employee_id == employee_id)
        .order_by(EmployeeVersion.version_number.desc())
        .limit(1)
    ).scalar_one_or_none()
    version_number = (last_version or 0) + 1
    from app.schemas.business_profile import BusinessProfile
    from app.services.business_profile_render import render_profile_facts

    ws_knowledge = workspace_knowledge_text(db, workspace_id)
    profile_dict = draft.business_profile if isinstance(draft.business_profile, dict) else None
    if profile_dict:
        from app.services.profile_publish_validation import validate_profile_publishable

        problems = validate_profile_publishable(profile_dict)
        if problems:
            raise ValueError("Profile not publishable: " + "; ".join(problems))
    profile_facts = ""
    if profile_dict:
        profile_facts = render_profile_facts(BusinessProfile.from_snapshot(profile_dict))
    snapshot = {
        "brief": draft.brief,
        "operator_instructions": (draft.operator_instructions or "").strip() or None,
        "persona": draft.persona,
        "business_profile": profile_dict,
        "profile_facts": profile_facts or None,
        "language": draft.language,
        "natural_spoken": draft.natural_spoken,
        "mode": draft.mode.value if isinstance(draft.mode, CallMode) else draft.mode,
        "website_url": draft.website_url,
        "website_knowledge": (draft.website_knowledge or "").strip() or None,
        "website_fetched_at": noted_website_fetch(draft.website_url) or datetime.now(UTC).isoformat(),
        "workspace_knowledge": ws_knowledge or None,
        "revision": draft.revision,
        "tts_speaker": resolve_tts_speaker(draft.tts_speaker),
    }
    snapshot["version_number"] = version_number
    version = EmployeeVersion(
        employee_id=employee_id,
        workspace_id=workspace_id,
        version_number=version_number,
        snapshot=snapshot,
    )
    db.add(version)
    db.flush()
    employee.status = EmployeeStatus.published
    employee.active_version_id = version.id
    db.commit()
    db.refresh(version)
    db.refresh(employee)
    return version