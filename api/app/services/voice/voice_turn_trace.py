"""Per-turn provenance for PSTN / LLM-first — captured_fields + DB (30d)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models.call_turn_event import CallTurnEvent

logger = logging.getLogger(__name__)

RETENTION_DAYS = 30


def log_turn_event(
    fields: dict,
    *,
    turn: int,
    caller_text: str,
    agent_text: str,
    source: str,
    extra: dict | None = None,
) -> dict:
    row = {
        "turn": turn,
        "ts": datetime.now(UTC).isoformat(),
        "stt_final_text": (caller_text or "")[:2000],
        "stt_confidence": (extra or {}).get("stt_confidence"),
        "utterance_ms": (extra or {}).get("utterance_ms"),
        "caller": (caller_text or "")[:500],
        "agent": (agent_text or "")[:2000],
        "source": source,
        "provider": (extra or {}).get("provider"),
        "tools": (extra or {}).get("tools"),
        "guard_actions": (extra or {}).get("guard_actions"),
        "timings": (extra or {}).get("timings"),
        "errors": (extra or {}).get("errors"),
    }
    if extra:
        for k, v in extra.items():
            if k not in row:
                row[k] = v
    log = list(fields.get("voice_turn_trace") or [])
    log.append(row)
    fields["voice_turn_trace"] = log[-200:]
    fields["last_turn_source"] = source
    return fields


def persist_turn_trace_db(
    db: Session,
    *,
    call_id,
    workspace_id,
    turn_index: int,
    fields: dict,
) -> None:
    trace = fields.get("voice_turn_trace") or []
    if not trace:
        return
    row = trace[-1]
    try:
        db.add(
            CallTurnEvent(
                call_id=call_id,
                workspace_id=workspace_id,
                turn_index=turn_index,
                payload=row,
            )
        )
        db.commit()
        cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
        db.execute(delete(CallTurnEvent).where(CallTurnEvent.created_at < cutoff))
        db.commit()
    except Exception:
        logger.exception("persist_turn_trace_db failed call=%s", call_id)
        db.rollback()