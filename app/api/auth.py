from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.api.deps import LOGIN_LIMIT, enforce_rate_limit, get_current_user
from app.api.schemas import LoginRequest, TokenResponse
from app.db.database import get_db
from app.services.auth_service import authenticate, issue_token, revoke_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
    _rate: None = Depends(enforce_rate_limit(LOGIN_LIMIT)),
):
    user = authenticate(db, payload.email, payload.password)
    token = issue_token(db, user)
    return TokenResponse(token=token, user=user.public_dict())


@router.post("/logout")
def logout(
    user=Depends(get_current_user),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    if authorization and authorization.lower().startswith("bearer "):
        revoke_token(db, authorization.split(" ", 1)[1].strip())
    return {"ok": True}
