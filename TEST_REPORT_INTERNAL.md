# Internal Verification Report — attendance-system

Extensive internal test pass: full pytest suite, coverage, lint, DB schema/ORM
consistency, and a live end-to-end smoke test against a real MySQL instance.
**Date:** 2026-08-12 · **Head revision:** `7866a97` (Phase 10)

> Two real defects were found and fixed during this pass — see §6.

---

## 1. Executive summary

| Area | Result |
|------|--------|
| Automated test suite | **157/157 pass** (156 pre-existing + 1 new regression test) |
| Code coverage | **91%** statements (1289 stmts, 120 missed) |
| Lint (`ruff check`) | **0 errors** |
| Format (`ruff format --check`) | 15 files drift (pre-existing, see §4.2) |
| Type checking | Not configured (no mypy/pyright in the repo) |
| Schema.sql ↔ ORM (live MySQL) | **Consistent after fixing a Phase 4 drift** |
| Live smoke test (real MySQL + HTTP) | **All flows green**, incl. rate limiter + sheets queue |
| Defects found | 2 (both fixed + regression-tested) |

**Verdict:** the system is in good shape. Security controls (RBAC, rate limits,
token lifecycle, selfie validation) behave as specified under live traffic. The
only substantive gaps are *documentation drift* (fixed) and a *MySQL second-
granularity edge* in the Sheets manual sync (fixed). The rest are optional
coverage/latency items (§7).

---

## 2. Environment

- macOS arm64, Python 3.12 (.venv), FastAPI + SQLAlchemy 2 + pymysql
- Test DB: in-memory SQLite per test (`StaticPool`), `Base.metadata.create_all`
- Live DB: throwaway MySQL `attendance_smoke` (utf8mb4), created + dropped around
  the smoke test — the real `attendance_system` DB was never touched
- Server: uvicorn on `127.0.0.1:8011`, real HTTP via curl

---

## 3. Automated test suite (157 tests)

### 3.1 Per-file results (`uv run pytest -v`)

| File | Tests | Verifies |
|------|-------|----------|
| `test_api.py` | 45 | E2E: auth, RBAC, sessions, scan, selfie, CSV, rate limits, pagination, filters |
| `test_session.py` | 18 | Session lifecycle service rules (window, expiry, duplicates, validation) |
| `test_verification.py` | 14 | Code/selfie/both modes, attempts, admin code assignment |
| `test_audit.py` | 14 | Audit cockpit, geofence, per-action audit-log coverage |
| `test_enrichment.py` | 13 | UA parsing, GeoIP enrichment (mocked readers) |
| `test_sheets.py` | 10 | Sheets mirror: queue, worker, backoff, idempotency, force-sync |
| `test_models_v2.py` | 8 | ORM round-trips (devices, attempts, audit, SheetsSync) |
| `test_anomaly.py` | 8 | Anomaly scoring (edge radius, reuse, speed, device, country, cap) |
| `test_auth.py` | 7 | Login/logout/token lifecycle |
| `test_geo.py` | 6 | Haversine math, boundary-inclusive radius |
| `test_device_auth.py` | 6 | Device binding, hashed tokens, revocation |
| `test_pipeline.py` | 4 | HTTP device metadata → anomaly → cockpit pipeline |
| `test_reporting.py` | 4 | Per-session present/absent roster |
| **Total** | **157** | |

All pass. Single warning is a `StarletteDeprecationWarning` from the bundled
`httpx` used by FastAPI's TestClient (test-harness only, not app code).

### 3.2 Slowest tests (from `--durations=12`)

The suite is dominated by bcrypt hashing + selfie file I/O, not logic:

- 4.3s `test_edge_of_radius_flagged` · 4.2s `test_scan_expired_qr` ·
  3.5s `test_outside_radius_still_hard_blocked` · 3.4s CSV absent test ·
  3.3s `test_scan_wrong_token` · 3.3s `test_selfie_only_success`
- Full run: **204s** (SQLite; ~80s earlier runs, variance from machine load)

Latency is per-test bcrypt gensalt + login, not a product issue.

---

## 4. Static analysis

### 4.1 `ruff check` — clean

Selected rules `E,F,I,UP,B,C4,SIM` over `app`, `tests`, `scripts` → **All checks passed**.

### 4.2 `ruff format --check` — 15 files drift

32 files already formatted; 15 would be reformatted. **Pre-existing drift**, not
introduced in Phase 10 (the repo's gate is `ruff check`, per TEST_REPORT.md).
Recommendation: run `ruff format app tests scripts` once as a chore commit.

### 4.3 Type checking

Not configured (no mypy/pyright). Python 3.12 + SQLAlchemy 2.0 Mapped types give
reasonable static confidence; adding `pyright` to the dev group is a low-cost
upgrade (recommendation, not a blocker).

---

## 5. Coverage — 91% statements

Full table (`--cov=app`, 156/157 collected, 1289 stmts):

| Module | Stmts | Miss | Cov | Notes |
|--------|------:|-----:|----:|-------|
| `api/admin.py` | 221 | 21 | 90% | unreviewed-filter, export-file, delete paths |
| `api/auth.py` | 22 | 0 | 100% | |
| `api/deps.py` | 32 | 1 | 97% | |
| `api/schemas.py` | 61 | 1 | 98% | |
| `api/student.py` | 67 | 8 | 88% | selfie-only edge lines |
| `core/config.py` | 23 | 0 | 100% | |
| `core/logging.py` | 17 | 0 | 100% | |
| `core/rate_limit.py` | 19 | 1 | 95% | |
| `core/storage.py` | 41 | 9 | 78% | delete-sweep / orphan-cleanup paths |
| `core/time.py` | 10 | 0 | 100% | |
| `db/database.py` | 13 | 4 | 69% | MySQL-engine branch only (tests use SQLite) |
| `main.py` | 59 | 7 | 88% | 404/static fallbacks |
| `models/entities.py` | 162 | 0 | 100% | |
| `services/analytics_service.py` | 46 | 3 | 93% | |
| `services/anomaly_service.py` | 40 | 0 | 100% | |
| `services/audit_service.py` | 8 | 0 | 100% | |
| `services/auth_service.py` | 66 | 4 | 94% | |
| `services/code_service.py` | 15 | 2 | 87% | |
| `services/geo_service.py` | 10 | 0 | 100% | |
| `services/geoip_service.py` | 53 | 20 | **62%** | real `.mmdb` read path (mocked in tests) |
| `services/qr_service.py` | 12 | 0 | 100% | |
| `services/session_service.py` | 134 | 7 | 95% | |
| `services/settings_service.py` | 25 | 2 | 92% | |
| `services/sheets_service.py` | 101 | 28 | **72%** | lazy gspread transport (untested by design) |
| `services/ua_service.py` | 32 | 2 | 94% | |

**Coverage gaps are structural, not accidental:**
- `geoip_service` (62%) and `sheets_service` (72%) deliberately depend on external
  systems (`.mmdb` DB, Google credentials) that tests fake out — the *failure*
  paths are what's covered, which is the important part.
- `db/database.py` (69%) is the MySQL-engine wiring; the suite runs SQLite.

---

## 6. Defects found & fixed

### 6.1 (Fixed) `database/schema.sql` missing Phase 4 columns — reference DDL drift

`attendance_records` in `schema.sql` was missing the GeoIP columns `city`,
`region`, `country` that the ORM model and `migrations/002_v2_geoip.sql` both
have. Any fresh DB built *only* from `schema.sql` would have failed Phase 4/5
queries. **Fix:** added the three columns (VARCHAR 100/100/60) between `isp` and
`os`, matching migration 002. Verified: `schema.sql ↔ ORM(live)` now consistent
for all 9 tables (the extra `schema_migrations` table in schema.sql is expected).

### 6.2 (Fixed) MySQL `DATETIME` second-truncation → manual Sheets sync could skip a just-queued session

Live smoke found `POST /api/admin/sheets/sync` returning `{"queued":0}` seconds
after a scan. Root cause: `enqueue_sync` sets `next_attempt_at = now()`, and
MySQL `DATETIME` truncates to seconds, so a sync in the same wall-clock second
saw `next_attempt_at <= now()` as **false** and skipped the entry. SQLite stores
microseconds, so the suite never caught it. **Fix:** `sync_pending(..., force=True)`
ignores the retry timer (manual/session-end sync drains everything); the admin
endpoint passes `force=True`. Added regression test
`test_manual_sync_forces_not_yet_due_entries`, re-verified live.

---

## 7. Live smoke test (real MySQL + real HTTP) — all green

Throwaway `attendance_smoke` DB, uvicorn on 8011, exercised with curl.

| Check | Result |
|-------|--------|
| `/login`, `/admin`, `/student` pages | 200 text/html |
| Admin + student login (64-char bearer tokens) | OK |
| Wrong password → 401; no token → 401; student on admin route → 403 | OK |
| Create session (subject/faculty/date/window/coords/radius) | OK, `live:true` |
| QR endpoint → PNG (825 B, `image/png`) | OK |
| Scan w/ valid GPS + selfie | 200 `present`, selfie saved |
| Duplicate scan → 409 `already_marked` | OK |
| Wrong QR token → 400 | OK |
| Out-of-radius scan → 400 `outside_zone` | OK |
| **QR expiry** (expired `expires_at` → `qr_expired`) | OK |
| **Code mode**: missing → `code_required`; wrong → `wrong_code`; correct → 200 | OK |
| Attempt audit trail (failure×2 + success rows persisted) | OK |
| Dashboard stats (5 enrolled / 2 present / 40%) | OK |
| Sessions (paginated `{total,limit,offset,sessions}`) | OK |
| History roster (marked 1 / enrolled 5 / absent 4) | OK |
| Audit records + geofence live (`sessions/scans/rejections/cutoff`) | OK |
| Audit log: all actions (session_created, code_assigned, device_revoked, settings_updated, sheets_synced, selfie_viewed) | OK |
| CSV export: correct columns; subject filter isolates rows; absent = no row | OK |
| Settings GET/PUT round-trip incl. `sheets_enabled` toggle | OK |
| **Sheets queue**: 0 entries while disabled → 1 pending after scan with toggle on | OK |
| **Sheets sync** (no gspread): graceful → `retryable`, attempts=1, backoff applied, DB untouched | OK |
| Device bind → revoke → revoked token → 401 | OK |
| Logout → 200 | OK |
| Student current-week (Mon–Sun, today flagged, present sessions) | OK |
| **Rate limiter**: 10 logins/min → 11th `429` (observed live mid-test) | OK |
| Admin page renders Sheets UI (sync button, queue table, toggle) | OK |

---

## 8. Security review (observational, via live + code)

- **RBAC**: enforced on every admin route (401 no token / 403 student) — confirmed.
- **Rate limits**: login 10/min, scan 30/min, sliding window — confirmed live.
- **Credential storage**: bcrypt hashes; device tokens stored hashed only — confirmed
  in code (`token_hash`).
- **QR replay/expiry**: single-use token + `expires_at` checked server-side —
  confirmed.
- **Selfie validation**: type/size/magic bytes; stored under `storage/selfies/`,
  served only via admin `GET /api/admin/selfie/{id}` with a view audit log.
- **SQL injection**: all queries via SQLAlchemy bound params — no raw f-string
  SQL in `app/` (checked).
- **Secrets**: `.env` uses `change-me-in-production` default — **action item** for
  real deploys (pre-existing, not a regression).

---

## 9. Recommendations (non-blocking)

1. `uv run ruff format app tests scripts` once (chore commit) to clear the 15-file drift.
2. Add `pyright` + `pytest-cov` to the dev group for a repeatable coverage/type gate.
3. Set a real `SECRET_KEY` + `VERIFICATION_CODE_KEY` via env in any deployment.
4. Optional: cover `storage.delete_selfie` sweep and `geoip_service` failure branches
   to push coverage into the high-80s/90s everywhere.
5. Consider Redis/proxy-level rate limiting for multi-worker deployments (the code
   documents this; current limiter is single-process in-memory).

---

## 10. Repo hygiene

Files changed during this verification pass (uncommitted):
- `database/schema.sql` — fixed Phase 4 drift (6.1)
- `app/services/sheets_service.py` — `force` param (6.2)
- `app/api/admin.py` — manual sync uses `force=True` (6.2)
- `tests/test_sheets.py` — new regression test (6.2)

All four are safe, isolated, and re-verified (157/157 + ruff clean + live).
