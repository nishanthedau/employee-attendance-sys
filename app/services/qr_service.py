"""QR code generation (PNG) from a session's payload."""

import io
import json

import segno

from app.models.entities import AttendanceSession


def session_payload(session: AttendanceSession) -> dict:
    """Payload embedded in the QR code; the token is only ever issued here
    and must match the DB row at scan time."""
    return {"session_id": session.id, "qr_token": session.qr_token}


def render_session_qr(session: AttendanceSession, scale: int = 10) -> bytes:
    payload = json.dumps(session_payload(session))
    qr = segno.make_qr(payload, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=scale, border=2)
    return buf.getvalue()
