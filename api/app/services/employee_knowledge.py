"""Employee knowledge: brief, website analysis, workspace sources — pin + voice grounding."""

from __future__ import annotations

import hashlib
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Call, Employee, EmployeeVersion, KnowledgeSource

MAX_WORKSPACE_KNOWLEDGE_CHARS = 8_000

# Published website text, keyed by workspace, employee, and source version.
_WEBSITE_CACHE: dict[tuple[str, str, str], str] = {}


def cached_website_knowledge(
    *,
    workspace_id: object,
    employee_id: object,
    snapshot: dict,
) -> str:
    web = str(snapshot.get("website_knowledge") or "").strip()
    token = "|".join(
        [
            str(snapshot.get("revision") or ""),
            str(snapshot.get("version_number") or ""),
            hashlib.sha256(web.encode()).hexdigest()[:12],
            str(snapshot.get("website_url") or ""),
        ]
    )
    key = (str(workspace_id), str(employee_id), token)
    cached = _WEBSITE_CACHE.get(key)
    if cached is not None:
        return cached
    _WEBSITE_CACHE[key] = web
    if len(_WEBSITE_CACHE) > 128:
        _WEBSITE_CACHE.pop(next(iter(_WEBSITE_CACHE)))
    return web


def workspace_knowledge_text(db: Session, workspace_id: UUID) -> str:
    """All ready workspace knowledge sources, newest sections last."""
    rows = db.scalars(
        select(KnowledgeSource)
        .where(KnowledgeSource.workspace_id == workspace_id)
        .order_by(KnowledgeSource.created_at.asc())
    ).all()
    parts: list[str] = []
    for row in rows:
        body = (row.content or "").strip()
        if not body:
            continue
        title = (row.title or "Knowledge").strip()
        parts.append(f"### {title}\n{body}")
    text = "\n\n".join(parts)
    if len(text) > MAX_WORKSPACE_KNOWLEDGE_CHARS:
        text = text[:MAX_WORKSPACE_KNOWLEDGE_CHARS] + "\n…"
    return text


def combine_supplemental_knowledge(*parts: str | None) -> str:
    chunks: list[str] = []
    for part in parts:
        s = (part or "").strip()
        if s:
            chunks.append(s)
    return "\n\n".join(chunks)


def knowledge_metrics(
    *,
    brief: str,
    website_knowledge: str | None,
    workspace_knowledge: str | None,
) -> dict[str, int]:
    b = (brief or "").strip()
    w = (website_knowledge or "").strip()
    ws = (workspace_knowledge or "").strip()
    supplemental = combine_supplemental_knowledge(w, ws)
    return {
        "brief_chars": len(b),
        "website_chars": len(w),
        "workspace_chars": len(ws),
        "supplemental_chars": len(supplemental),
        "total_grounding_chars": len(b) + len(supplemental),
    }


def snapshot_for_employee(db: Session, employee_id: UUID) -> dict | None:
    """Published EmployeeVersion snapshot, else current draft."""
    from app.services.employees import get_draft

    employee = db.get(Employee, employee_id)
    if not employee:
        return None
    if employee.active_version_id:
        version = db.get(EmployeeVersion, employee.active_version_id)
        if version and version.snapshot:
            return dict(version.snapshot)
    draft = get_draft(db, employee_id)
    if not draft:
        return None
    return {
        "brief": draft.brief,
        "language": draft.language,
        "natural_spoken": draft.natural_spoken,
        "mode": draft.mode.value if hasattr(draft.mode, "value") else draft.mode,
        "website_url": draft.website_url,
        "website_knowledge": draft.website_knowledge,
        "revision": draft.revision,
        "tts_speaker": draft.tts_speaker,
        "operator_instructions": getattr(draft, "operator_instructions", "") or "",
        "persona": getattr(draft, "persona", None),
        "business_profile": getattr(draft, "business_profile", None),
    }


def _fields_from_snapshot(
    db: Session,
    call: Call,
    snap: dict,
    *,
    preview: bool,
) -> dict:
    from app.schemas.business_profile import BusinessProfile
    from app.services.business_profile_render import render_profile_facts
    from app.services.voice.voice_facts import build_spoken_facts_block, persona_from_brief

    fields = dict(call.captured_fields or {})
    workspace_id = getattr(call, "workspace_id", None)
    snap = {
        **snap,
        "website_knowledge": cached_website_knowledge(
            workspace_id=workspace_id,
            employee_id=getattr(call, "employee_id", None),
            snapshot=snap,
        ),
    }
    supplemental, _web, ws = supplemental_for_inbound(
        snap,
        db,
        workspace_id,
        prefer_frozen_workspace=False,
    )
    brief = str(snap.get("brief") or "")
    profile_raw = snap.get("business_profile")
    profile_facts = str(snap.get("profile_facts") or "").strip()
    if profile_raw and not profile_facts:
        profile_facts = render_profile_facts(BusinessProfile.from_snapshot(profile_raw))
    operator = str(snap.get("operator_instructions") or "").strip()
    if profile_facts:
        spoken_facts = profile_facts
        if ws:
            spoken_facts = f"{spoken_facts}\n\n{ws}".strip()
    else:
        spoken_facts = build_spoken_facts_block(
            brief=brief,
            website_knowledge=supplemental,
            workspace_knowledge=ws,
            strip_hacks=not bool(profile_raw),
        )
    persona = snap.get("persona") if isinstance(snap.get("persona"), dict) else None
    if not persona:
        persona = persona_from_brief(brief)
    out = {
        **fields,
        "employee_brief": brief,
        "employee_operator_instructions": operator or persona.get("instructions", ""),
        "employee_language": str(snap.get("language") or fields.get("employee_language") or "English"),
        "employee_website_knowledge": supplemental,
        "employee_workspace_knowledge": ws,
        "employee_spoken_facts": spoken_facts,
        "employee_business_profile": profile_raw,
        "employee_persona": persona,
        "employee_website_url": str(snap.get("website_url") or ""),
        "employee_snapshot_revision": str(snap.get("revision") or ""),
        "employee_version_number": str(snap.get("version_number") or ""),
        "knowledge_state": "draft" if preview else "published",
        "knowledge_content_version": hashlib.sha256(spoken_facts.encode()).hexdigest()[:12],
        "knowledge_source_url": str(snap.get("website_url") or ""),
        "knowledge_fetched_at": str(snap.get("website_fetched_at") or ""),
        "voice_grounding_pinned": True,
    }
    return out


def pin_call_voice_grounding(db: Session, call: Call) -> dict:
    """Load published (or preview draft) snapshot once per PSTN call."""
    fields = dict(call.captured_fields or {})
    if fields.get("voice_grounding_pinned"):
        return fields
    employee_id = getattr(call, "employee_id", None)
    if not employee_id:
        return fields
    preview = bool(fields.get("browser_preview"))
    snap = snapshot_for_employee(db, employee_id)
    if not snap:
        return fields
    if preview:
        from app.services.employees import get_draft

        draft = get_draft(db, employee_id)
        if draft:
            snap = {
                **snap,
                "brief": draft.brief,
                "website_knowledge": draft.website_knowledge,
                "website_url": draft.website_url,
                "revision": draft.revision,
                "natural_spoken": draft.natural_spoken,
                "mode": draft.mode.value if hasattr(draft.mode, "value") else draft.mode,
                "operator_instructions": getattr(draft, "operator_instructions", "") or "",
                "persona": getattr(draft, "persona", None),
                "business_profile": getattr(draft, "business_profile", None),
            }
    fields = _fields_from_snapshot(db, call, snap, preview=preview)
    call.captured_fields = fields
    db.commit()
    db.refresh(call)
    return fields


def refresh_call_grounding(db: Session, call: Call) -> dict:
    """
    Re-pin brief + supplemental knowledge from DB so publish/workspace edits apply on the next turn.
    Live PSTN: published brief + website from version, workspace sources always fresh.
    Browser preview: draft brief/website + live workspace.
    """
    fields = dict(call.captured_fields or {})
    if fields.get("voice_grounding_pinned") and not fields.get("browser_preview"):
        return fields
    if fields.get("browser_preview"):
        fields.pop("voice_grounding_pinned", None)
        call.captured_fields = fields
    return pin_call_voice_grounding(db, call)


def supplemental_for_inbound(
    snapshot: dict,
    db: Session,
    workspace_id: UUID,
    *,
    prefer_frozen_workspace: bool = False,
) -> tuple[str, str, str]:
    """
    Returns (supplemental_for_llm, website_part, workspace_part).
    Old published snapshots without workspace_knowledge get a live workspace backfill.
    """
    web = str(snapshot.get("website_knowledge") or "").strip()
    frozen_ws = str(snapshot.get("workspace_knowledge") or "").strip()
    if prefer_frozen_workspace and frozen_ws:
        ws = frozen_ws
    elif not frozen_ws:
        ws = workspace_knowledge_text(db, workspace_id)
    else:
        ws = frozen_ws
    supplemental = combine_supplemental_knowledge(web, ws)
    return supplemental, web, ws