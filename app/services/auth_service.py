"""Authentication: opaque bearer tokens stored in the auth_tokens table."""

import secrets
import uuid
from datetime import datetime, timedelta

import bcrypt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import AuthToken, Role, User

TOKEN_TTL_HOURS = 12


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401):
        self.message = message
        self.status_code = status_code


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def issue_token(db: Session, user: User) -> str:
    token = secrets.token_hex(32)
    db.add(
        AuthToken(
            user_id=user.id,
            token=token,
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(hours=TOKEN_TTL_HOURS),
        )
    )
    db.commit()
    return token


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.execute(select(User).where(User.email == email.lower())).scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        raise AuthError("Invalid email or password")
    return user


def get_user_by_token(db: Session, token: str) -> User | None:
    record = (
        db.execute(
            select(AuthToken).where(AuthToken.token == token, AuthToken.expires_at > datetime.now())
        )
        .scalar_one_or_none()
    )
    return record.user if record else None


def revoke_token(db: Session, token: str) -> None:
    db.query(AuthToken).filter(AuthToken.token == token).delete()
    db.commit()


def require_role(user: User, role: Role) -> None:
    if user.role != role:
        raise AuthError("Forbidden", status_code=403)
