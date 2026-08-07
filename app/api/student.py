from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import SCAN_LIMIT, enforce_rate_limit, get_current_user
from app.core.storage import delete_selfie, save_selfie
from app.db.database import get_db
from app.models.entities import User
from app.services.analytics_service import current_week
from app.services.session_service import scan_attendance

router = APIRouter(prefix="/api/student", tags=["student"])


@router.post("/attendance/scan")
def scan(
    session_id: int = Form(...),
    qr_token: str = Form(min_length=1, max_length=128),
    latitude: float = Form(ge=-90, le=90),
    longitude: float = Form(ge=-180, le=180),
    selfie: UploadFile = File(...),
    student: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _rate: None = Depends(enforce_rate_limit(SCAN_LIMIT)),
):
    """Mark attendance for the authenticated student — server re-verifies QR,
    expiry, session window, duplicates, and GPS. The identity comes from the
    bearer token, never from client input. A selfie photo is required and is
    validated (type/size/magic bytes) and stored on disk before the checks run."""
    filename = save_selfie(selfie)
    try:
        record = scan_attendance(
            db,
            session_id=session_id,
            qr_token=qr_token,
            student=student,
            lat=latitude,
            lng=longitude,
            selfie_path=filename,
        )
    except Exception:
        # Any validation failure after the file was written must not leak
        # orphaned photos on disk.
        delete_selfie(filename)
        raise
    return {
        "ok": True,
        "message": "Attendance marked",
        "record": {
            "session_id": record.session_id,
            "scan_time": record.scan_time.isoformat(),
            "status": record.status,
            "selfie": record.selfie_path is not None,
        },
    }


@router.get("/attendance/current-week")
def my_week(student: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return current_week(db, student.id)
