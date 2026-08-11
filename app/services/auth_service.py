"""Authentication: opaque bearer tokens stored in the auth_tokens table."""

import hashlib
import secrets
from datetime import timedelta

import bcrypt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import now
from app.models.entities import AuthToken, DeviceRegistration, Role, User

TOKEN_TTL_HOURS = 12

# Device "login once" tokens never expire by design; a re-auth only happens
# after an admin revokes the device. We still refresh last_seen_at, but at most
# every few minutes to keep request churn low.
LAST_SEEN_REFRESH_SECONDS = 300


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401, code: str = "auth_error"):
        self.message = message
        self.status_code = status_code
        self.code = code


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_user(db: Session, name: str, email: str, password: str, role: Role) -> User:
    user = User(
        name=name,
        email=email.lower(),
        password_hash=hash_password(password),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def issue_token(db: Session, user: User) -> str:
    token = secrets.token_hex(32)
    db.add(
        AuthToken(
            user_id=user.id,
            token=token,
            created_at=now(),
            expires_at=now() + timedelta(hours=TOKEN_TTL_HOURS),
        )
    )
    db.commit()
    return token


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.execute(select(User).where(User.email == email.lower())).scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        raise AuthError("Invalid email or password", code="invalid_credentials")
    return user


def get_user_by_token(db: Session, token: str) -> User | None:
    auth = (
        db.execute(
            select(AuthToken).where(AuthToken.token == token, AuthToken.expires_at > now())
        )
        .scalar_one_or_none()
    )
    if auth:
        return auth.user

    device = (
        db.execute(
            select(DeviceRegistration).where(
                DeviceRegistration.token_hash == hash_token(token),
                DeviceRegistration.is_active.is_(True),
            )
        )
        .scalar_one_or_none()
    )
    if device:
        if (
            device.last_seen_at is None
            or (now() - device.last_seen_at).total_seconds() > LAST_SEEN_REFRESH_SECONDS
        ):
            device.last_seen_at = now()
            db.commit()
        return device.user
    return None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def register_device(db: Session, user: User, meta: dict, ip: str | None) -> tuple[str, DeviceRegistration]:
    """Bind a new device to a user, returning (plaintext token, device row)."""
    token = secrets.token_hex(32)
    device = DeviceRegistration(
        user_id=user.id,
        token_hash=hash_token(token),
        device_name=(meta.get("device_name") or "")[:255] or None,
        os=(meta.get("os") or "")[:50] or None,
        os_version=(meta.get("os_version") or "")[:50] or None,
        browser=(meta.get("browser") or "")[:50] or None,
        browser_version=(meta.get("browser_version") or "")[:50] or None,
        model=(meta.get("model") or "")[:100] or None,
        screen=(meta.get("screen") or "")[:30] or None,
        language=(meta.get("language") or "")[:10] or None,
        ip=ip,
        last_seen_at=now(),
        is_active=True,
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return token, device


def revoke_token(db: Session, token: str) -> None:
    db.query(AuthToken).filter(AuthToken.token == token).delete()
    db.commit()


def require_role(user: User, role: Role) -> None:
    if user.role != role:
        raise AuthError("You don't have permission to do that.", status_code=403, code="forbidden")
