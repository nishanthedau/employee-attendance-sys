from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import SCAN_LIMIT, enforce_rate_limit, get_current_user
from app.core.storage import delete_selfie, save_selfie
from app.db.database import get_db
from app.models.entities import User
from app.services.analytics_service import current_week
from app.services.session_service import record_scan, validate_scan

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
    """Mark attendance for the authenticated student.

    All cheap validations (QR token, session window, QR expiry, duplicate, GPS
    radius) run *before* the selfie is written to disk, so a rejected scan never
    leaves an orphaned photo. Identity comes from the bearer token, never from
    client input."""
    session = validate_scan(db, session_id, qr_token, student, latitude, longitude)
    filename = save_selfie(selfie)
    try:
        record = record_scan(db, session, student, latitude, longitude, filename)
    except Exception:
        # Persistence failed (e.g. a concurrent duplicate scan hit the unique
        # constraint) — the photo was already written, so clean it up.
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
