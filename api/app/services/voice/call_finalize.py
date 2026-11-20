"""Idempotent call finalization from WSS stop, disconnect, or Exotel status callback."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import Call
from app.models.enums import CallOutcome

logger = logging.getLogger(__name__)

_TERMINAL = frozenset(
    {
        CallOutcome.completed,
        CallOutcome.failed,
        CallOutcome.no_answer,
        CallOutcome.busy,
        CallOutcome.canceled,
    }
)


def finalize_call_idempotent(
    db: Session,
    call: Call,
    *,
    duration_seconds: int | None = None,
    outcome: CallOutcome | None = None,
    source: str = "unknown",
) -> Call:
    """
    Whichever path arrives first sets finalized_at + duration + outcome.
    Later paths only fill missing fields and never shorten duration.
    """
    if not call:
        return call
    changed = False
    if outcome is not None:
        oc = outcome if isinstance(outcome, CallOutcome) else CallOutcome(str(outcome))
        if call.finalized_at and call.outcome in _TERMINAL:
            pass
        elif call.outcome is None or str(getattr(call.outcome, "value", call.outcome)) in (
            "connected",
            "queued",
            "dialing",
            "ringing",
        ):
            call.outcome = oc
            changed = True
        elif not call.finalized_at:
            call.outcome = oc
            changed = True

    if duration_seconds is not None and duration_seconds >= 0:
        dur = max(int(duration_seconds), 1)
        prev = int(call.duration_seconds or 0)
        if dur > prev:
            call.duration_seconds = dur
            changed = True
        elif not call.duration_seconds:
            call.duration_seconds = dur
            changed = True

    if not call.finalized_at:
        oc = call.outcome
        if oc in _TERMINAL:
            call.finalized_at = datetime.now(UTC)
            changed = True
        elif duration_seconds and duration_seconds > 0:
            call.finalized_at = datetime.now(UTC)
            if call.outcome is None or str(getattr(call.outcome, "value", call.outcome)) == "connected":
                call.outcome = CallOutcome.completed
            changed = True

    fields = dict(call.captured_fields or {})
    if fields.get("finalize_source") != source:
        fields["finalize_source"] = source
        changed = True
    call.captured_fields = fields

    if changed:
        db.commit()
        db.refresh(call)
        logger.info(
            "call_finalize id=%s source=%s duration=%s outcome=%s",
            call.id,
            source,
            call.duration_seconds,
            call.outcome,
        )
    return call