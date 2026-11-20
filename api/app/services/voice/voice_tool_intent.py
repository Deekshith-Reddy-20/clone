"""Safety-net tool triggers only (manager/human, explicit hangup)."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models import Call
from app.services.voice.voice_safety_net import manager_callback_intent
from app.services.voice.voice_tools import execute_tool

logger = logging.getLogger(__name__)


def apply_intent_tools(
    db: Session,
    call: Call,
    fields: dict,
    caller_text: str,
    lang: str,
    spoken: str,
) -> tuple[str, dict, bool]:
    t = (caller_text or "").strip()
    low = t.lower()
    hang = False
    out = spoken
    fired: list[str] = []

    def run(name: str, args: dict | None = None) -> None:
        nonlocal out, fields, hang
        s, fields, h = execute_tool(
            db,
            call,
            fields,
            name,
            args or {},
            caller_text=t,
            lang=lang,
            tool_source="intent_layer",
        )
        fired.append(name)
        if s and (not out or name in ("transfer_to_human", "end_call")):
            out = s
        hang = hang or h

    if manager_callback_intent(t):
        run("transfer_to_human", {})
    elif low in {"goodbye", "bye", "bye bye"} or t in ("అంతే చాలు",):
        run("end_call", {})

    if fired:
        fields["intent_layer_fired"] = True
        log = list(fields.get("intent_layer_log") or [])
        log.extend(fired)
        fields["intent_layer_log"] = log[-20:]
        logger.info("intent_layer_fired call=%s tools=%s", getattr(call, "id", None), fired)
    return out, fields, hang