from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from app.api.deps import LOGIN_LIMIT, enforce_rate_limit, get_current_user, require_student
from app.api.schemas import DeviceRegisterRequest, DeviceTokenResponse, LoginRequest, TokenResponse
from app.db.database import get_db
from app.models.entities import User
from app.services.auth_service import authenticate, issue_token, register_device, revoke_token

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


@router.post("/device", response_model=DeviceTokenResponse)
def bind_device(
    payload: DeviceRegisterRequest,
    request: Request,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """Bind this phone to the signed-in employee.

    The returned device token replaces the short-lived login token and stays
    valid until an admin revokes the device — the employee never logs in again.
    """
    device_token, device = register_device(db, student, payload.model_dump(), request.client.host)
    return DeviceTokenResponse(device_token=device_token, device_id=device.id)


@router.post("/logout")
def logout(
    user=Depends(get_current_user),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    if authorization and authorization.lower().startswith("bearer "):
        revoke_token(db, authorization.split(" ", 1)[1].strip())
    return {"ok": True}
