from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.schemas import LoginRequest, TokenResponse
from app.db.database import get_db
from app.services.auth_service import (
    AuthError,
    authenticate,
    issue_token,
    revoke_token,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    try:
        user = authenticate(db, payload.email, payload.password)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
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
