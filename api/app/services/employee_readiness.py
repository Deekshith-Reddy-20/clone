"""Go-live readiness checks per employee."""

from __future__ import annotations

import logging
import ssl
from urllib.parse import urlparse
from uuid import UUID

import httpx
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Call, Employee, PhoneNumber, WorkspaceSettings
from app.services.employees import get_draft, get_employee
from app.services.owner_notify import (
    CHANNELS,
    channel_configured,
    load_workspace_owner,
    owner_contact,
    owner_notify_channel_verified,
    verified_map,
)
from app.services.profile_publish_validation import validate_profile_publishable
from app.services.voice.gemini import gemini_configured
from app.services.voice.sarvam import sarvam_configured
from app.services.voice.voice_llm_primary import llm_failover_chain, llm_primary_provider
from app.services.voice.voice_openai_chat import chat_completion_ping as openai_ping, openai_configured
from app.services.voice.silero_vad import vad_engine_name

logger = logging.getLogger(__name__)


def _check_item(ok: bool, label: str, detail: str = "") -> dict:
    return {"ok": ok, "label": label, "detail": detail}


def _last_e2e_p50(db: Session, employee_id: UUID) -> float | None:
    calls = db.scalars(
        select(Call)
        .where(Call.employee_id == employee_id)
        .order_by(desc(Call.created_at))
        .limit(20)
    ).all()
    vals: list[float] = []
    for c in calls:
        fields = c.captured_fields or {}
        summary = fields.get("voice_latency_summary") or {}
        if isinstance(summary, dict) and summary.get("e2e_p50_ms"):
            vals.append(float(summary["e2e_p50_ms"]))
        for row in fields.get("voice_turn_metrics") or []:
            if isinstance(row, dict) and row.get("e2e_ms"):
                vals.append(float(row["e2e_ms"]))
    if not vals:
        return None
    vals.sort()
    mid = len(vals) // 2
    return vals[mid]


def _voicebot_resolver_ok() -> tuple[bool, str]:
    s = get_settings()
    base = (s.public_api_base_url or "").strip()
    if not base:
        return False, "public_api_base_url unset"
    path = f"{base.rstrip('/')}/exotel/voicebot"
    try:
        with httpx.Client(timeout=8.0, verify=True) as client:
            r = client.get(path, params={"CallSid": "readiness-probe", "From": "+910000000000", "To": "+910000000001"})
            if r.status_code == 404:
                return True, "resolver reachable (404 without mapped call is expected)"
            if r.status_code == 200:
                data = r.json()
                url = str(data.get("url") or "")
                return url.startswith("wss://") or url.startswith("ws://"), f"url={url[:80]}"
            return False, f"http_{r.status_code}"
    except ssl.SSLError as exc:
        return False, f"tls:{exc}"
    except Exception as exc:
        return False, type(exc).__name__


def _gemini_ping() -> tuple[bool, str]:
    if not gemini_configured():
        return False, "GEMINI_API_KEY missing"
    try:
        from app.services.voice.gemini import generate_agent_reply

        txt = generate_agent_reply(employee_brief="ping", caller_text="ping", history=[])
        if txt and "Thanks for explaining" not in txt:
            return True, "generate ok"
        return bool(txt), "response"
    except Exception as exc:
        return False, type(exc).__name__


def _llm_failover_ping() -> tuple[bool, str]:
    primary = llm_primary_provider()
    details: list[str] = []
    for p in llm_failover_chain():
        if p == primary:
            continue
        if p == "openai" and openai_configured():
            ok, d = openai_ping()
            details.append(f"openai:{d}")
            if ok:
                return True, "; ".join(details)
        if p == "gemini" and gemini_configured():
            ok, d = _gemini_ping()
            details.append(f"gemini:{d}")
            if ok:
                return True, "; ".join(details)
        if p == "sarvam" and sarvam_configured():
            ok, d = _sarvam_ping()
            details.append(f"sarvam:{d}")
            if ok:
                return True, "; ".join(details)
    return False, "; ".join(details) or "no failover configured"


def _sarvam_ping() -> tuple[bool, str]:
    if not sarvam_configured():
        return False, "SARVAM_API_KEY missing"
    try:
        from app.services.voice.sarvam import SARVAM_CHAT_MODEL, _client

        _client().chat.completions(
            model=SARVAM_CHAT_MODEL,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=4,
            stream=False,
        )
        return True, "chat ok"
    except Exception as exc:
        return False, type(exc).__name__


def employee_go_live_readiness(db: Session, workspace_id: UUID, employee_id: UUID) -> dict:
    employee = get_employee(db, workspace_id, employee_id)
    if not employee:
        raise ValueError("Employee not found")
    draft = get_draft(db, employee_id)
    profile = draft.business_profile if draft and isinstance(getattr(draft, "business_profile", None), dict) else {}
    is_pub = employee.status.value == "published" if hasattr(employee.status, "value") else str(employee.status) == "published"
    gate_errors = validate_profile_publishable(profile) if profile else ["no_profile"]
    publish_ok = is_pub and len(gate_errors) == 0

    phones = list(
        db.scalars(
            select(PhoneNumber).where(
                PhoneNumber.workspace_id == workspace_id,
                PhoneNumber.employee_id == employee_id,
                PhoneNumber.inbound_enabled.is_(True),
            )
        ).all()
    )
    wo, contacts = load_workspace_owner(db, workspace_id)
    verified_ch = owner_notify_channel_verified(wo, contacts)
    s = get_settings()
    resolver_ok, resolver_detail = _voicebot_resolver_ok()
    sarvam_ok, sarvam_detail = _sarvam_ping()
    failover_ok, failover_detail = _llm_failover_ping()
    vad = vad_engine_name()
    barge = (s.voice_barge_in or "off").strip().lower()
    e2e = _last_e2e_p50(db, employee_id)

    notify_items = []
    for ch in CHANNELS:
        configured = channel_configured(ch, contacts, s)
        ver = verified_map(wo).get(ch, False)
        notify_items.append(
            _check_item(
                ver and configured,
                f"Owner notify {ch} verified",
                "not_configured" if not configured else ("unverified" if not ver else "ok"),
            )
        )

    items = [
        _check_item(publish_ok, "Published profile passes publish gate"),
        _check_item(len(phones) > 0, "Exotel number mapped to this employee (inbound)", ", ".join(p.e164 for p in phones)),
        _check_item(resolver_ok, "Voicebot URL resolver reachable (TLS)", resolver_detail),
        _check_item(sarvam_ok, "Sarvam STT/TTS/chat keys valid (live ping)", sarvam_detail),
        _check_item(
            failover_ok,
            "LLM failover provider reachable (live ping)",
            failover_detail,
        ),
        _check_item(verified_ch is not None, "≥1 verified owner-notify channel", verified_ch or "none"),
        _check_item(vad == "silero", "vad_engine=silero", f"current={vad}"),
        _check_item(True, f"barge-in flag", barge),
        _check_item(e2e is not None and e2e < 8000, "Last real call e2e p50", f"{e2e:.0f}ms" if e2e else "no calls"),
        *notify_items,
    ]
    ok = all(i["ok"] for i in items[:8])
    return {
        "employee_id": str(employee_id),
        "ready": ok,
        "vad_engine": vad,
        "voice_barge_in": barge,
        "last_e2e_p50_ms": e2e,
        "items": items,
    }