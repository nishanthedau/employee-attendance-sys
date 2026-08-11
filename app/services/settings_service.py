"""Org-level settings (single row, id=1): verification mode, defaults, toggles."""

from sqlalchemy.orm import Session

from app.models.entities import OrgSettings, VerificationMode


def get_org_settings(db: Session) -> OrgSettings:
    """Fetch the single org-settings row, creating it on first use."""
    settings = db.get(OrgSettings, 1)
    if settings is None:
        settings = OrgSettings(id=1)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def update_org_settings(db: Session, **fields) -> OrgSettings:
    settings = get_org_settings(db)
    mode = fields.get("verification_mode")
    if mode is not None and not isinstance(mode, VerificationMode):
        try:
            mode = VerificationMode(mode)
        except ValueError as exc:
            raise ValueError(f"Unknown verification mode: {mode}") from exc
        fields["verification_mode"] = mode
    for key, value in fields.items():
        if hasattr(settings, key):
            setattr(settings, key, value)
    db.commit()
    db.refresh(settings)
    return settings
