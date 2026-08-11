"""FastAPI dependencies: current-user resolution from bearer token."""

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.rate_limit import RateLimiter
from app.db.database import get_db
from app.models.entities import DeviceRegistration, Role, User
from app.services.auth_service import get_device_by_token, get_user_by_token, require_role

LOGIN_LIMIT = RateLimiter(max_requests=10, window_seconds=60)
SCAN_LIMIT = RateLimiter(max_requests=30, window_seconds=60)


def enforce_rate_limit(limiter: RateLimiter):
    def dependency(request: Request) -> None:
        key = f"{limiter.max_requests}:{request.client.host if request.client else 'unknown'}"
        if not limiter.allow(key):
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Please wait about a minute and try again.",
            )
    return dependency


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Please sign in to continue.")
    token = authorization.split(" ", 1)[1].strip()
    user = get_user_by_token(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    require_role(user, Role.admin)
    return user


def require_student(user: User = Depends(get_current_user)) -> User:
    require_role(user, Role.student)
    return user


def get_request_device(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> DeviceRegistration | None:
    """Resolve the bound device behind the token, if any (session tokens have none)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return get_device_by_token(db, authorization.split(" ", 1)[1].strip())
