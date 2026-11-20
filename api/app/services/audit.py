from uuid import UUID

from sqlalchemy.orm import Session

from app.models import AuditEvent


def log_audit(
    db: Session,
    *,
    workspace_id: UUID,
    actor_user_id: UUID | None,
    action: str,
    summary: str,
) -> None:
    db.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            action=action,
            summary=summary,
        )
    )
    db.commit()