"""Per-turn voice trace (30-day retention)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Uuid, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CallTurnEvent(Base):
    __tablename__ = "call_turn_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    turn_index: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())