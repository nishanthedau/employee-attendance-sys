"""Phase 10: Google Sheets mirror — queue on scan, worker push, retry/backoff,
idempotency (no duplicate rows), manual/session-end sync, DB independence."""

import base64
from datetime import date, timedelta

from app.core.time import now
from app.models.entities import (
    AttendanceRecord,
    AttendanceSession,
    OrgSettings,
    Role,
    SheetsSync,
)
from app.services.auth_service import create_user
from app.services.sheets_service import (
    enqueue_sync,
    sync_pending,
    sync_session,
)

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
LAT, LNG = 28.6139, 77.2090


class FakeSheets:
    """In-memory spreadsheet transport. Mirrors the real client: a push
    overwrites the sheet contents, so re-pushing can never duplicate rows."""

    def __init__(self):
        self.created = []
        self.pushed = {}
        self.fail_next = 0

    def ensure_sheet(self, title):
        self.created.append(title)
        return f"sheet-{len(self.created)}"

    def push_rows(self, spreadsheet_id, rows):
        if self.fail_next:
            self.fail_next -= 1
            raise ConnectionError("Google Sheets timeout")
        self.pushed[spreadsheet_id] = [list(r) for r in rows]


def _enable_sheets(db_session):
    settings = db_session.get(OrgSettings, 1) or OrgSettings(id=1)
    settings.sheets_enabled = True
    db_session.add(settings)
    db_session.commit()


def _headers(client, db_session, email, name, role):
    create_user(db_session, name, email, "secret123", role)
    login = client.post("/api/auth/login", json={"email": email, "password": "secret123"}).json()
    return {"Authorization": f"Bearer {login['token']}"}


def _admin(client, db_session):
    return _headers(client, db_session, "admin@x.com", "Admin", Role.admin)


def _student(client, db_session, email="stu@x.com"):
    return _headers(client, db_session, email, "Stu", Role.student)


def _session(client, ah):
    return client.post(
        "/api/admin/attendance/create",
        headers=ah,
        json={
            "subject": "DBMS",
            "faculty": "Prof. Rao",
            "date": date.today().isoformat(),
            "start_time": "00:00:00",
            "end_time": "23:59:00",
            "latitude": LAT,
            "longitude": LNG,
            "radius_meters": 75,
            "qr_expiry_minutes": 3,
        },
    ).json()


def _scan(client, headers, session_id, token):
    data = {"session_id": str(session_id), "qr_token": token, "latitude": str(LAT), "longitude": str(LNG)}
    files = {"selfie": ("s.png", PNG, "image/png")}
    return client.post("/api/student/attendance/scan", data=data, files=files, headers=headers)


def _token(db, session_id):
    return db.get(AttendanceSession, session_id).qr_token


def _sync_for(db, session_id):
    return db.query(SheetsSync).filter(SheetsSync.session_id == session_id).one()


def _record_count(db, session_id):
    return db.query(AttendanceRecord).filter(AttendanceRecord.session_id == session_id).count()

def test_scan_enqueues_sync_when_enabled(client, db_session, tmp_selfie_storage):
    _enable_sheets(db_session)
    ah = _admin(client, db_session)
    sh = _student(client, db_session)
    session = _session(client, ah)
    assert _scan(client, sh, session["id"], _token(db_session, session["id"])).status_code == 200

    sync = _sync_for(db_session, session["id"])
    assert sync.status == "pending"
    assert sync.attempts == 0
    # Attendance is unaffected by the mirror — the record exists regardless.
    assert _record_count(db_session, session["id"]) == 1


def test_no_queue_when_disabled(client, db_session, tmp_selfie_storage):
    ah = _admin(client, db_session)
    sh = _student(client, db_session)
    session = _session(client, ah)
    assert _scan(client, sh, session["id"], _token(db_session, session["id"])).status_code == 200
    assert db_session.query(SheetsSync).filter(SheetsSync.session_id == session["id"]).count() == 0


def test_manual_sync_forces_not_yet_due_entries(client, db_session, tmp_selfie_storage):
    """MySQL DATETIME truncates to seconds, so a freshly-enqueued entry can be
    'not yet due'. Manual/session-end sync must drain it anyway (force=True)."""
    _enable_sheets(db_session)
    ah = _admin(client, db_session)
    sh = _student(client, db_session)
    session = _session(client, ah)
    assert _scan(client, sh, session["id"], _token(db_session, session["id"])).status_code == 200

    # Put the retry timer one second in the future — like a just-committed scan.
    sync = _sync_for(db_session, session["id"])
    sync.next_attempt_at = now() + timedelta(seconds=1)
    db_session.commit()

    sheets = FakeSheets()
    assert sync_pending(db_session, client=sheets)["synced"] == 0  # not due for the worker
    assert sync_pending(db_session, client=sheets, force=True)["synced"] == 1  # manual drains it
    assert _sync_for(db_session, session["id"]).status == "synced"


def test_worker_pushes_records(client, db_session, tmp_selfie_storage):
    _enable_sheets(db_session)
    ah = _admin(client, db_session)
    sh = _student(client, db_session)
    session = _session(client, ah)
    assert _scan(client, sh, session["id"], _token(db_session, session["id"])).status_code == 200

    sheets = FakeSheets()
    summary = sync_pending(db_session, client=sheets)
    assert summary["synced"] == 1

    sync = _sync_for(db_session, session["id"])
    assert sync.status == "synced"
    assert sync.spreadsheet_id
    rows = sheets.pushed[sync.spreadsheet_id]
    assert rows[0] == ["scan_time", "employee", "email", "subject", "faculty", "date", "status"]
    assert rows[1][1] == "Stu" and rows[1][2] == "stu@x.com"


def test_sheets_failure_keeps_attendance_and_retries(client, db_session, tmp_selfie_storage):
    _enable_sheets(db_session)
    ah = _admin(client, db_session)
    sh = _student(client, db_session)
    session = _session(client, ah)
    assert _scan(client, sh, session["id"], _token(db_session, session["id"])).status_code == 200
    assert _record_count(db_session, session["id"]) == 1

    sheets = FakeSheets()
    sheets.fail_next = 1
    summary = sync_pending(db_session, client=sheets)
    assert summary["synced"] == 0
    assert summary["retryable"] == 1

    sync = _sync_for(db_session, session["id"])
    assert sync.status == "pending"
    assert sync.attempts == 1
    assert sync.next_attempt_at is not None
    assert "timeout" in (sync.last_error or "").lower()

    # Nothing pushed yet, nothing duplicated.
    assert all(len(rows) == 0 for rows in sheets.pushed.values())

    # Backoff timer fires: the retry is due again and drains successfully.
    sync = _sync_for(db_session, session["id"])
    sync.next_attempt_at = now() - timedelta(seconds=1)
    db_session.commit()
    summary = sync_pending(db_session, client=sheets)
    assert summary["synced"] == 1
    assert _record_count(db_session, session["id"]) == 1


def test_retry_backoff_increases(client, db_session, tmp_selfie_storage):
    _enable_sheets(db_session)
    ah = _admin(client, db_session)
    sh = _student(client, db_session)
    session = _session(client, ah)
    assert _scan(client, sh, session["id"], _token(db_session, session["id"])).status_code == 200

    sheets = FakeSheets()
    sync = _sync_for(db_session, session["id"])
    delays = []
    sheets.fail_next = 3
    for _ in range(3):
        sync = sync_session(db_session, sync, client=sheets)
        delays.append(sync.next_attempt_at)
    assert sync.attempts == 3
    first, second, third = delays
    assert first < second < third  # exponential backoff
    assert sync.status == "pending"


def test_retry_does_not_duplicate_rows(client, db_session, tmp_selfie_storage):
    _enable_sheets(db_session)
    ah = _admin(client, db_session)
    sh = _student(client, db_session)
    session = _session(client, ah)
    assert _scan(client, sh, session["id"], _token(db_session, session["id"])).status_code == 200

    sheets = FakeSheets()
    assert sync_pending(db_session, client=sheets)["synced"] == 1
    sync = _sync_for(db_session, session["id"])
    sheet_id = sync.spreadsheet_id
    assert len(sheets.pushed[sheet_id]) == 2  # header + one row

    # Re-running the drain on an already-synced session is a no-op.
    assert sync_pending(db_session, client=sheets) == {"queued": 0, "synced": 0, "retryable": 0, "failed": 0}
    assert len(sheets.pushed[sheet_id]) == 2

    # Even if a late scan re-queues an already-synced session, the push is a
    # full overwrite — the sheet still holds header + one row, never duplicates.
    enqueue_sync(db_session, session["id"])
    assert sync_pending(db_session, client=sheets)["synced"] == 1
    assert len(sheets.pushed[sheet_id]) == 2
    assert sheets.pushed[sheet_id][1][2] == "stu@x.com"
    assert _record_count(db_session, session["id"]) == 1


def test_manual_session_end_sync(client, db_session, tmp_selfie_storage, monkeypatch):
    _enable_sheets(db_session)
    ah = _admin(client, db_session)
    sh = _student(client, db_session)
    session = _session(client, ah)
    assert _scan(client, sh, session["id"], _token(db_session, session["id"])).status_code == 200

    from app.services import sheets_service

    fake = FakeSheets()
    monkeypatch.setattr(sheets_service, "get_client", lambda: fake)
    res = client.post(f"/api/admin/sheets/sync?session_id={session['id']}", headers=ah)
    assert res.status_code == 200
    assert res.json()["summary"]["synced"] == 1

    sync = _sync_for(db_session, session["id"])
    assert sync.status == "synced"
    # Manual sync is audit-logged.
    log = client.get("/api/admin/audit/log", headers=ah).json()
    assert any(e["action"] == "sheets_synced" for e in log)


def test_sheets_outage_does_not_affect_db(client, db_session, tmp_selfie_storage, monkeypatch):
    _enable_sheets(db_session)
    ah = _admin(client, db_session)
    sh = _student(client, db_session)
    session = _session(client, ah)

    # A scan while Sheets is broken still succeeds and stays the source of truth.
    assert _scan(client, sh, session["id"], _token(db_session, session["id"])).status_code == 200
    assert _record_count(db_session, session["id"]) == 1
    assert db_session.query(AttendanceRecord).first().status == "present"

    from app.services import sheets_service

    def boom():
        raise RuntimeError("gspread not configured")

    monkeypatch.setattr(sheets_service, "get_client", boom)
    sync = _sync_for(db_session, session["id"])
    sync_session(db_session, sync)
    assert sync.status == "pending"
    assert sync.attempts == 1
    assert db_session.query(AttendanceRecord).first().status == "present"  # DB untouched


def test_sync_requires_admin(client, db_session):
    sh = _student(client, db_session)
    assert client.post("/api/admin/sheets/sync", headers=sh).status_code == 403
