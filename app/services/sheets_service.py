"""Google Sheets mirror: per-session queue + worker with retry/backoff.

A scan that succeeds adds (or re-queues) a `SheetsSync` row. The worker
(`sync_pending`) pushes the session's rows to a spreadsheet exactly once:
already-synced sessions are a no-op, so retries can never duplicate rows.
Failures stay `pending` with exponential backoff and a capped attempt count.

The spreadsheet transport is behind a small client interface so the whole
pipeline is testable without Google credentials.
"""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import now
from app.models.entities import AttendanceRecord, AttendanceSession, SheetsSync, User

BACKOFF_BASE_SECONDS = 30
MAX_ATTEMPTS = 5


def enqueue_sync(db: Session, session_id: int) -> SheetsSync:
    """Create (or re-open) the queue entry for a session. Idempotent."""
    sync = db.execute(
        select(SheetsSync).where(SheetsSync.session_id == session_id)
    ).scalar_one_or_none()
    if sync is None:
        sync = SheetsSync(session_id=session_id, status="pending", next_attempt_at=now())
        db.add(sync)
    else:
        sync.status = "pending"
        sync.next_attempt_at = now()
        sync.last_error = None
    db.commit()
    db.refresh(sync)
    return sync


def _backoff_seconds(attempts: int) -> int:
    return BACKOFF_BASE_SECONDS * (2 ** (attempts - 1))


def _rows(session: AttendanceSession, records) -> list[list]:
    header = ["scan_time", "employee", "email", "subject", "faculty", "date", "status"]
    body = [
        [
            r.scan_time.strftime("%Y-%m-%d %H:%M:%S"),
            u.name,
            u.email,
            session.subject,
            session.faculty,
            session.date.isoformat(),
            r.status,
        ]
        for r, u in records
    ]
    return [header, *body]


def _records_for(db: Session, session_id: int):
    return db.execute(
        select(AttendanceRecord, User)
        .join(User, AttendanceRecord.student_id == User.id)
        .where(AttendanceRecord.session_id == session_id)
        .order_by(AttendanceRecord.id)
    ).all()


def _sheet_title(session: AttendanceSession) -> str:
    return f"Attendance - {session.subject} {session.date.isoformat()}"


def sync_session(db: Session, sync: SheetsSync, client=None) -> SheetsSync:
    """Push one queued session to Sheets. Already-synced sessions are a no-op."""
    if sync.status == "synced":
        return sync
    session = db.get(AttendanceSession, sync.session_id)
    if session is None:
        sync.status = "failed"
        sync.last_error = "session no longer exists"
        sync.next_attempt_at = None
        db.commit()
        db.refresh(sync)
        return sync
    try:
        if client is None:
            client = get_client()
        sheet_id = sync.spreadsheet_id or client.ensure_sheet(_sheet_title(session))
        client.push_rows(sheet_id, _rows(session, _records_for(db, sync.session_id)))
    except Exception as exc:  # noqa: BLE001 — any transport error is retryable
        sync.attempts += 1
        sync.last_error = str(exc)[:500]
        sync.status = "pending" if sync.attempts < MAX_ATTEMPTS else "failed"
        sync.next_attempt_at = now() + timedelta(seconds=_backoff_seconds(sync.attempts))
        db.commit()
        db.refresh(sync)
        return sync
    sync.status = "synced"
    sync.spreadsheet_id = sheet_id
    sync.last_error = None
    sync.next_attempt_at = None
    db.commit()
    db.refresh(sync)
    return sync


def sync_pending(db: Session, limit: int = 50, client=None) -> dict:
    """Process every due queue entry. Returns a small run summary."""
    due = (
        db.execute(
            select(SheetsSync)
            .where(SheetsSync.status == "pending", SheetsSync.next_attempt_at <= now())
            .order_by(SheetsSync.next_attempt_at)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    synced = retryable = failed = 0
    for entry in due:
        sync_session(db, entry, client=client)
        if entry.status == "synced":
            synced += 1
        elif entry.status == "failed":
            failed += 1
        else:
            retryable += 1
    return {"queued": len(due), "synced": synced, "retryable": retryable, "failed": failed}


# ---------- Transport client ----------


@dataclass
class SheetResult:
    spreadsheet_id: str


class SheetsClient:
    """Minimal Google Sheets transport. gspread is loaded lazily so the app
    works (and the queue drains to `failed`) without credentials installed."""

    def __init__(self, gspread=None):
        self._gspread = gspread

    def _spreadsheet(self):
        if self._gspread is None:
            try:
                import gspread
            except ImportError as exc:
                raise RuntimeError(
                    "gspread is not installed; configure Google Sheets to sync."
                ) from exc
            self._gspread = gspread
        return self._gspread

    def ensure_sheet(self, title: str) -> str:
        gc = self._spreadsheet()
        try:
            sheet = gc.open(title)
        except Exception:
            sheet = gc.create(title)
        return sheet.id

    def push_rows(self, spreadsheet_id: str, rows: list[list]):
        sheet = self._spreadsheet().open_by_key(spreadsheet_id).sheet1
        sheet.clear()
        sheet.append_rows(rows)


_client: SheetsClient | None = None


def get_client() -> SheetsClient:
    global _client
    if _client is None:
        _client = SheetsClient()
    return _client
