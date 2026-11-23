"""Ensure the staging Phase-1 inbound connection exists (idempotent)."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.outpero import OutperoAgent, OutperoInboundConnection

logger = logging.getLogger(__name__)


def ensure_inbound_connection(db: Session) -> OutperoInboundConnection | None:
    settings = get_settings()
    key = (settings.outpero_inbound_connection_key or "harish-staging").strip()
    if not key:
        return None

    existing = db.execute(
        select(OutperoInboundConnection).where(OutperoInboundConnection.connection_key == key)
    ).scalar_one_or_none()

    agent = db.execute(
        select(OutperoAgent).where(OutperoAgent.status == "active").order_by(OutperoAgent.created_at)
    ).scalars().first()
    if agent is None:
        logger.warning("outpero_inbound_bootstrap_no_agent")
        return existing

    did = (settings.outpero_inbound_did_e164 or "").strip() or "+00000000000"
    secret = (settings.outpero_inbound_webhook_secret or "").strip() or None

    if existing is None:
        existing = OutperoInboundConnection(
            id=uuid.uuid4(),
            connection_key=key,
            workspace_id=agent.workspace_id,
            outpero_agent_id=agent.id,
            employee_slug=agent.slug,
            did_e164=did,
            signing_secret=secret,
            enabled=True,
            phase="inbound_call_import_v1",
            config={"bootstrapped": True},
        )
        db.add(existing)
    else:
        existing.workspace_id = agent.workspace_id
        existing.outpero_agent_id = agent.id
        existing.employee_slug = agent.slug
        if did and did != "+00000000000":
            existing.did_e164 = did
        if secret:
            existing.signing_secret = secret
        existing.enabled = True

    db.commit()
    db.refresh(existing)
    logger.info(
        "outpero_inbound_connection_ready key=%s workspace=%s employee=%s",
        existing.connection_key,
        existing.workspace_id,
        existing.employee_slug,
    )
    return existing
