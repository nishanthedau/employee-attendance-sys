from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.schemas import ScanRequest
from app.db.database import get_db
from app.models.entities import User
from app.services.analytics_service import current_week
from app.services.session_service import SessionError, scan_attendance

router = APIRouter(prefix="/api/student", tags=["student"])


@router.post("/attendance/scan")
def scan(payload: ScanRequest, student: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Mark attendance for the authenticated student — server re-verifies QR,
    expiry, session window, duplicates, and GPS. The identity comes from the
    bearer token, never from client input."""
    try:
        record = scan_attendance(
            db,
            session_id=payload.session_id,
            qr_token=payload.qr_token,
            student=student,
            lat=payload.latitude,
            lng=payload.longitude,
        )
    except SessionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {
        "ok": True,
        "message": "Attendance marked",
        "record": {
            "session_id": record.session_id,
            "scan_time": record.scan_time.isoformat(),
            "status": record.status,
        },
    }


@router.get("/attendance/current-week")
def my_week(student: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return current_week(db, student.id)
