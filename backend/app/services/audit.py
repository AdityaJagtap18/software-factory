import uuid

from sqlalchemy.orm import Session as DBSession

from app.models.audit import AuditLog


def record(
    db: DBSession,
    *,
    action: str,
    target_type: str,
    target_id: str,
    actor_user_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    extra: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            actor_user_id=actor_user_id,
            organization_id=organization_id,
            extra=extra or {},
        )
    )
