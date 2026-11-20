"""Notify workspace owner: WhatsApp → SMS → email (verified channels only)."""

from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import WorkspaceSettings

logger = logging.getLogger(__name__)

CHANNELS = ("whatsapp", "sms", "email")


def _owner_blob(row: WorkspaceSettings | None) -> dict:
    if not row:
        return {}
    notes = row.notifications if isinstance(row.notifications, dict) else {}
    owner = notes.get("owner")
    return owner if isinstance(owner, dict) else {}


def owner_contact(
    workspace_owner: dict,
    settings: Settings | None = None,
) -> dict[str, str]:
    s = settings or get_settings()
    return {
        "whatsapp": str(workspace_owner.get("whatsapp") or s.owner_notify_whatsapp or "").strip(),
        "sms": str(workspace_owner.get("phone") or s.owner_notify_phone or "").strip(),
        "email": str(workspace_owner.get("email") or s.owner_notify_email or "").strip(),
    }


def verified_map(workspace_owner: dict) -> dict[str, bool]:
    raw = workspace_owner.get("verified")
    if not isinstance(raw, dict):
        return {c: False for c in CHANNELS}
    return {c: bool(raw.get(c)) for c in CHANNELS}


def channel_credentials_ready(channel: str, settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    if channel == "email":
        to = (s.owner_notify_email or "").strip()
        host = (s.smtp_host or "").strip()
        user = (s.smtp_user or "").strip()
        pw = (s.smtp_password or "").strip()
        return bool(to and host and user and pw)
    if channel == "sms":
        phone = (s.owner_notify_phone or "").strip()
        return bool(
            phone
            and s.exotel_api_key
            and s.exotel_api_token
            and s.exotel_account_sid
            and s.exotel_subdomain
            and s.exotel_caller_id
        )
    if channel == "whatsapp":
        phone = (s.owner_notify_whatsapp or "").strip()
        return bool(
            phone
            and s.exotel_api_key
            and s.exotel_api_token
            and getattr(s, "exotel_whatsapp_enabled", False)
        )
    return False


def channel_configured(
    channel: str,
    contacts: dict[str, str],
    settings: Settings | None = None,
) -> bool:
    addr = (contacts.get(channel) or "").strip()
    if not addr:
        return False
    return channel_credentials_ready(channel, settings)


def owner_notify_channel_verified(
    workspace_owner: dict,
    contacts: dict[str, str],
    settings: Settings | None = None,
) -> str | None:
    verified = verified_map(workspace_owner)
    for ch in CHANNELS:
        if verified.get(ch) and channel_configured(ch, contacts, settings):
            return ch
    return None


def manager_callback_minutes(
    workspace_owner: dict | None = None,
    contacts: dict[str, str] | None = None,
    settings: Settings | None = None,
) -> int | None:
    wo = workspace_owner or {}
    contacts = contacts or owner_contact(wo, settings)
    if owner_notify_channel_verified(wo, contacts, settings) is None:
        return None
    s = settings or get_settings()
    return max(1, int(s.manager_callback_minutes or 15))


def load_workspace_owner(db: Session, workspace_id: UUID | None) -> tuple[dict, dict[str, str]]:
    if not workspace_id:
        return {}, owner_contact({})
    row = db.execute(
        select(WorkspaceSettings).where(WorkspaceSettings.workspace_id == workspace_id)
    ).scalar_one_or_none()
    wo = _owner_blob(row)
    return wo, owner_contact(wo)


def notify_owner(
    *,
    subject: str,
    body: str,
    settings: Settings | None = None,
    workspace_owner: dict | None = None,
    contacts: dict[str, str] | None = None,
    force_channel: str | None = None,
) -> tuple[str, str]:
    """Returns (notify_status, channel): sent|failed|not_configured|skipped."""
    s = settings or get_settings()
    wo = workspace_owner or {}
    contacts = contacts or owner_contact(wo, s)
    ch = force_channel or owner_notify_channel_verified(wo, contacts, s)
    if not ch:
        if any((contacts.get(c) or "").strip() for c in CHANNELS):
            return "not_configured", "unverified"
        return "skipped", "none"
    if not channel_configured(ch, contacts, s):
        return "not_configured", ch
    text = f"{subject}\n\n{body}"[:4000]
    try:
        if ch == "whatsapp":
            return _notify_whatsapp(s, contacts["whatsapp"], text)
        if ch == "sms":
            return _notify_sms(s, contacts["sms"], text)
        return _notify_email(s, contacts["email"], subject, body)
    except Exception as exc:
        logger.warning("owner_notify failed ch=%s err=%s", ch, exc)
        return "failed", ch


def send_test_notification(
    channel: str,
    *,
    settings: Settings | None = None,
    contacts: dict[str, str],
) -> tuple[str, str]:
    s = settings or get_settings()
    ch = channel.strip().lower()
    if ch not in CHANNELS:
        return "failed", ch
    if not channel_configured(ch, contacts, s):
        return "not_configured", ch
    subj = "Karyuk owner notify test"
    body = "This is a test notification from Karyuk voice settings."
    if ch == "whatsapp":
        return _notify_whatsapp(s, contacts["whatsapp"], body)
    if ch == "sms":
        return _notify_sms(s, contacts["sms"], body)
    return _notify_email(s, contacts["email"], subj, body)


def _notify_email(s: Settings, to: str, subject: str, body: str) -> tuple[str, str]:
    if not to:
        return "not_configured", "email"
    host = (s.smtp_host or "").strip()
    user = (s.smtp_user or "").strip()
    pw = (s.smtp_password or "").strip()
    if not (host and user and pw):
        logger.info("owner_notify email not_configured to=%s", to[:24])
        return "not_configured", "email"
    msg = MIMEText(body)
    msg["Subject"] = subject[:120]
    msg["From"] = user
    msg["To"] = to
    with smtplib.SMTP(host, int(s.smtp_port or 587), timeout=15) as smtp:
        smtp.starttls()
        smtp.login(user, pw)
        smtp.sendmail(user, [to], msg.as_string())
    return "sent", "email"


def _notify_sms(s: Settings, phone: str, text: str) -> tuple[str, str]:
    if not phone or not channel_credentials_ready("sms", s):
        return "not_configured", "sms"
    url = f"https://{s.exotel_subdomain}.exotel.com/v1/Accounts/{s.exotel_account_sid}/Sms/send.json"
    with httpx.Client(timeout=20.0, auth=(s.exotel_api_key, s.exotel_api_token)) as client:
        r = client.post(url, data={"From": s.exotel_caller_id, "To": phone, "Body": text[:1400]})
        if r.status_code >= 400:
            return "failed", "sms"
    return "sent", "sms"


def _notify_whatsapp(s: Settings, phone: str, text: str) -> tuple[str, str]:
    if not phone or not channel_credentials_ready("whatsapp", s):
        return "not_configured", "whatsapp"
    url = f"https://{s.exotel_subdomain}.exotel.com/v1/Accounts/{s.exotel_account_sid}/Messages/send"
    with httpx.Client(timeout=20.0, auth=(s.exotel_api_key, s.exotel_api_token)) as client:
        r = client.post(
            url,
            json={
                "From": getattr(s, "exotel_whatsapp_from", "") or s.exotel_caller_id,
                "To": phone,
                "Body": text[:4000],
            },
        )
        if r.status_code >= 400:
            return "failed", "whatsapp"
    return "sent", "whatsapp"


def mark_channel_verified(notifications: dict, channel: str, *, status: str) -> dict:
    notes = dict(notifications or {})
    owner = dict(notes.get("owner") or {})
    verified = dict(owner.get("verified") or {})
    tests = dict(owner.get("last_test") or {})
    if status == "sent":
        verified[channel] = True
    tests[channel] = status
    owner["verified"] = verified
    owner["last_test"] = tests
    notes["owner"] = owner
    return notes