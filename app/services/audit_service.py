"""Audit logging for privileged actions (admin panel, settings, codes, devices)."""

from sqlalchemy.orm import Session

from app.models.entities import AuditLog, User


def log_action(
    db: Session,
    actor: User,
    action: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    details: dict | None = None,
    ip: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor.id,
        actor_role=actor.role.value,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
        ip=ip,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
