# Attendance System — Test Suite & Approach

Consolidated record of every automated test in the project (133 tests, all passing)
plus the methodology used to design them. Written for cross-verification with another
AI model.

**Repo:** `attendance-system` · **Stack:** FastAPI + SQLAlchemy + SQLite · **Runner:** pytest

---

## 1. How to run

```bash
uv run pytest -q            # full suite (133 tests, ~60s)
uv run pytest tests/test_api.py -q          # single file
uv run pytest tests/test_anomaly.py -k speed # single test by keyword
uv run ruff check app/ tests/               # lint gate
```

## 2. Approach / testing strategy

### 2.1 Test isolation (conftest.py)

- **In-memory SQLite per test** — `db_session` fixture builds a fresh engine
  (`sqlite://`, `StaticPool`) and creates all tables via `Base.metadata.create_all`.
  No test ever sees another test's data.
- **API client bound to that DB** — `client` fixture overrides FastAPI's
  `get_db` dependency with `app.dependency_overrides`, so every HTTP test runs
  against the same isolated DB the fixture is using.
- **Rate-limiter reset (autouse)** — login (10/min) and scan (30/min) limits live
  in process memory; `reset_rate_limits` clears `_hits` before every test so
  rate-limit tests are deterministic.
- **Selfie storage sandbox (autouse)** — `tmp_selfie_storage` monkeypatches the
  selfie directory to a per-test `tmp_path`, and is used by tests to assert
  "no orphaned files on disk" (an important leak check).
- **Shared helpers** — each feature file defines small builder helpers
  (`_auth`, `_session`, `_scan`, `student_token`, ...) so HTTP flows read like
  scripts: auth → create session → scan → assert.

### 2.2 Test layers

1. **Pure unit** — no DB/HTTP. e.g. haversine math (`test_geo`), UA parsing
   (`test_enrichment`), anomaly scoring (`test_anomaly`).
2. **Service/integration** — call services directly against `db_session`
   (`test_session`, `test_models_v2`) to verify business rules and error codes.
3. **Full HTTP/API** — `TestClient` end-to-end: auth, RBAC (403/401), validation
   (422), business errors (400/409), persistence, binary uploads, CSV export
   (`test_api`, `test_verification`, `test_audit`, `test_device_auth`).

### 2.3 Conventions used in every test

- **Error-code contracts**: the API returns a machine-readable `code`
  (`outside_zone`, `wrong_code`, `qr_expired`, ...). Tests assert the code, not
  just the status, so refactors of message text don't break tests.
- **RBAC matrix**: every admin route has a "student gets 403" test; every protected
  student route has a "no token → 401" test.
- **Boundary values**: radius boundary-inclusive, expiry `now-1s`, edge-of-radius
  at 89% distance, oversized images at `2MB+1`, etc.
- **Disk-leak guards**: rejected scans must not leave orphaned selfie files
  (`glob("*") == []`).
- **Deterministic time**: sessions are created "today 00:00–23:59" with an
  injected `now()`; single-use QR token expires_at set to `now-1s` to test expiry.
- **Real PNG bytes**: a 1×1 base64 PNG satisfies the server's magic-byte check;
  the oversized/fake-content tests prove the validator rejects garbage.

### 2.4 Coverage summary by area

| Area | Count |
|------|-------|
| API end-to-end (auth, RBAC, sessions, scan, selfie, CSV, rate limits) | 45 |
| Session lifecycle service rules | 18 |
| Verification modes (code/selfie/both) | 14 |
| Enrichment (UA + GeoIP) | 13 |
| Anomaly scoring | 8 |
| Audit cockpit + geofence | 8 |
| Model round-trips (v2 audit-layer models) | 8 |
| Device-bound auth | 6 |
| Geo math | 6 |
| Auth (login/logout/token) | 7 |
| **Total** | **133** |

---

## 3. Test files, every case

### 3.1 `tests/conftest.py` — shared fixtures
`db_session`, `client`, `reset_rate_limits` (autouse), `tmp_selfie_storage` (autouse).
(Not tests; described in §2.1.)

### 3.2 `tests/test_geo.py` — geo primitives (6)
| Test | Verifies |
|------|----------|
| `test_haversine_same_point_is_zero` | Same point → 0 m. |
| `test_haversine_delhi_mumbai_distance` | ~1,150–1,250 km (real-world sanity). |
| `test_haversine_close_points` | ~100 m resolution. |
| `test_within_radius_true` | Point inside → allowed. |
| `test_within_radius_false` | Point outside → blocked. |
| `test_boundary_inclusive` | Exactly on the boundary → allowed. |

### 3.3 `tests/test_auth.py` — authentication (7)
| Test | Verifies |
|------|----------|
| `test_login_success` | Valid creds → 200, token + user role. |
| `test_login_wrong_password` | Bad password → 401, friendly detail. |
| `test_login_invalid_email_rejected` | Non-email → 422 with `invalid_input`. |
| `test_login_missing_field_friendly_message` | Missing password → 422 string detail (not array). |
| `test_login_email_case_insensitive` | `STU@COMPANY.COM` logs in. |
| `test_protected_route_without_token` | No token → 401. |
| `test_logout_revokes_token` | Logout invalidates the token (subsequent 401). |

### 3.4 `tests/test_session.py` — session lifecycle service (18, incl. 6 parametrized)
| Test | Verifies |
|------|----------|
| `test_create_session_success` | 64-char QR token, future `expires_at`, creator recorded. |
| `test_fresh_qr_always_scannable` | Fresh QR valid for full duration, not clipped to window. |
| `test_create_session_validation_errors[6 cases]` | Past date / overnight (end<start) / lat>90 / lng<-180 / radius 0 / expiry 0 → `SessionError`. |
| `test_create_session_subject_blank` | Whitespace subject rejected. |
| `test_scan_success` | Valid scan → record `present`, linked to student. |
| `test_scan_stores_selfie_path` | Selfie path persisted. |
| `test_scan_wrong_qr_token` | 400 + `invalid_qr`. |
| `test_scan_unknown_session` | Nonexistent session → 400. |
| `test_scan_expired_qr` | Expired single-use token → "no longer open". |
| `test_scan_session_not_active` | Outside window → 400 + `session_not_active`. |
| `test_scan_duplicate` | Second scan → 409 + "already marked". |
| `test_scan_outside_zone` | 400 + `outside_zone`. |
| `test_scan_injects_now` | Tomorrow's session inactive today. |

### 3.5 `tests/test_models_v2.py` — v2 audit-layer models (8)
| Test | Verifies |
|------|----------|
| `test_org_settings_defaults` | Defaults: mode `none`, radius 75, sheets off, retention 90. |
| `test_org_settings_verification_modes` | Mode persists as `both`. |
| `test_user_verification_code_nullable` | Code fields nullable, round-trip. |
| `test_device_registration_roundtrip` | Device row + relationship + deactivate. |
| `test_attendance_attempt_roundtrip` | Failure attempt with full audit snapshot + timestamps. |
| `test_attendance_record_soft_gps_and_audit_fields` | Nullable lat/lng, verification + anomaly fields persist. |
| `test_audit_log_roundtrip` | Audit entry with details JSON. |
| `test_sheets_sync_roundtrip` | `SheetsSync` status lifecycle. |

### 3.6 `tests/test_device_auth.py` — device-bound auth (6)
| Test | Verifies |
|------|----------|
| `test_bind_device_returns_token` | `/api/auth/device` → device_token + id. |
| `test_device_token_works_on_protected_route` | Device token authorizes student routes. |
| `test_login_token_still_works_after_device_binding` | Both token types coexist. |
| `test_revoked_device_token_rejected` | Deactivated device → 401 "expired. Please sign in". |
| `test_device_token_stored_hashed` | Only a hash is stored (never the raw token). |
| `test_admin_cannot_bind_device` | Admins → 403. |

### 3.7 `tests/test_verification.py` — configurable verification (14)
| Test | Verifies |
|------|----------|
| `test_student_settings_reflects_org_mode` | Student sees org `verification_mode`. |
| `test_admin_can_read_and_update_settings` | PUT/GET settings round-trip (code, radius 120). |
| `test_admin_settings_rejects_bad_mode` | Unknown mode → 422. |
| `test_admin_assigns_and_views_code` | Assign + read back personal code. |
| `test_admin_auto_generates_code_when_blank` | Blank → auto 4+ digit code. |
| `test_admin_cannot_assign_code_to_admin` | Code assignment on admin → 404. |
| `test_scan_without_code_when_code_mode` | Missing code in `code` mode → 400 `code_required`. |
| `test_scan_wrong_code_rejected` | Wrong code → 400 `wrong_code`. |
| `test_scan_correct_code_success` | Correct code → 200, `verification_method_used=code`, `code_verified=true`. |
| `test_scan_no_code_assigned_yet` | No profile code → 400 `no_code_assigned`. |
| `test_scan_missing_selfie_when_selfie_mode` | No photo in `selfie` mode → 400 `selfie_required`. |
| `test_scan_mode_both_requires_selfie_and_code` | Both mode: missing code fails, both supplied succeeds → method `both`. |
| `test_failed_attempt_is_recorded` | Rejected scan writes an `AttendanceAttempt` (outcome failure, reason). |
| `test_successful_attempt_is_recorded` | Accepted scan writes success attempt. |

### 3.8 `tests/test_enrichment.py` — UA + GeoIP enrichment (13)
| Test | Verifies |
|------|----------|
| `test_parse_ua_iphone_safari` | iOS/Safari/iPhone parsed. |
| `test_parse_ua_android_chrome` | Android/Chrome/mobile. |
| `test_parse_ua_windows_edge` | Windows/Edge/Desktop. |
| `test_parse_ua_macos_firefox` | macOS/Firefox/Desktop. |
| `test_parse_ua_samsung` | Samsung Internet. |
| `test_parse_ua_empty` | None → empty dict (no crash). |
| `test_is_private_ip` | RFC1918 + loopback + "testclient" → private; public IPs → not. |
| `test_enrich_private_ip_empty` | Private IP → no lookup, `{}`. |
| `test_enrich_no_db_configured_empty` | Missing GeoLite DB → graceful `{}`. |
| `test_enrich_with_readers` | Fake readers → isp/city/region/country. |
| `test_enrich_reader_error_is_swallowed` | `AddressNotFoundError` doesn't 500. |
| `test_record_scan_stores_enriched_columns` | Enrichment columns land on the record (mocked). |
| `test_record_scan_without_enrichment` | Real HTTP scan: private test IP → geo skipped, UA still parsed. |

### 3.9 `tests/test_anomaly.py` — anomaly scoring (8)
| Test | Verifies |
|------|----------|
| `test_edge_of_radius_flagged` | ~89 m from center (radius 100) → flagged `edge_of_radius`, accepted. |
| `test_outside_radius_still_hard_blocked` | Beyond radius → still 400 `outside_zone`. |
| `test_reused_coordinates_flagged` | Same lat/lng across two sessions → `reused_coordinates`. |
| `test_assess_implausible_speed` | 33 km in 2 min (~990 km/h) → score ≥ 40 + `implausible_speed`. |
| `test_assess_new_device` | First scan on device 999 → score ≥ 10 + `new_device`. |
| `test_assess_country_change` | India → Singapore IP → score ≥ 30 + `ip_country_change`. |
| `test_clean_scan_scores_zero` | Baseline scan → score 0, no flags. |
| `test_score_capped_at_100` | Stacked flags cap at 100, all flags present. |

### 3.10 `tests/test_audit.py` — audit cockpit + geofence (8)
| Test | Verifies |
|------|----------|
| `test_audit_records_lists_enrichment` | Record row: employee/session joins, UA-derived `os`, anomaly 0, `reviewed=false`, method `none`. |
| `test_audit_records_filter_unreviewed_and_min_anomaly` | `unreviewed_only` → 1; `min_anomaly=1` → []. |
| `test_review_record` | POST review → `reviewed=true`, drops out of unreviewed filter. |
| `test_audit_attempts_captures_rejections` | Failed (outside_zone) + success attempts both listed. |
| `test_audit_log_returns_actions` | Session creation is logged (`session_created`). |
| `test_audit_requires_admin` | Student → 403. |
| `test_geofence_live_returns_sessions_scans_rejections` | Sessions w/ radius, scans w/ anomaly, rejections w/ reason. |
| `test_geofence_live_requires_admin` | Student → 403. |

### 3.11 `tests/test_api.py` — end-to-end API (45)
| Test | Verifies |
|------|----------|
| `test_student_cannot_create_session` | RBAC 403. |
| `test_create_session_and_qr` | Session create + QR PNG endpoint. |
| `test_scan_success_duplicate_409` | OK + selfie saved; duplicate → 409 `already_marked`, still 1 file. |
| `test_scan_outside_zone` | 400 + no orphaned selfie. |
| `test_scan_wrong_token` | 400 + no orphaned selfie. |
| `test_scan_expired_qr` | 400 `qr_expired`. |
| `test_selfie_only_success` | No-QR selfie endpoint works, persists, file saved. |
| `test_selfie_only_duplicate_409` | Duplicate selfie scan blocked. |
| `test_selfie_only_outside_zone_no_orphan` | 400 + no file. |
| `test_selfie_only_unknown_session` | 400 `session_not_active`. |
| `test_selfie_only_session_not_active` | Yesterday's session → 400. |
| `test_selfie_only_expired_session` | Expired → 400 `qr_expired`. |
| `test_live_sessions_endpoint` | Live list excludes expired. |
| `test_scan_without_selfie_succeeds_when_not_required` | No selfie when mode=none → OK. |
| `test_scan_invalid_selfie_type` | text/plain → 400 `invalid_selfie`. |
| `test_scan_oversized_selfie` | >2 MB → 400. |
| `test_scan_fake_image_content_type` | Bad magic bytes → 400. |
| `test_scan_without_gps_succeeds_when_absent` | Missing GPS → skip, still present. |
| `test_scan_invalid_token` | Bad bearer → 401. |
| `test_admin_can_view_selfie` | Admin can fetch selfie PNG; student → 403. |
| `test_admin_dashboard_and_sessions` | Dashboard + session list shapes. |
| `test_student_management` | Create/list/search/duplicate(409)/delete. |
| `test_export_csv` | CSV headers + columns. |
| `test_current_week_shape` | 7 days, today flagged. |
| `test_student_cannot_access_admin_apis` | 403. |
| `test_login_rate_limited` | 10 bad logins → 11th 429. |
| `test_scan_rate_limited` | 30+ scan attempts → 429. |
| `test_create_session_past_date_rejected` | Past date → 400 "past". |
| `test_create_session_end_before_start_rejected` | Overnight window → 422 `invalid_input`. |
| `test_create_session_invalid_radius_rejected` | radius 0 → 422. |
| `test_create_session_blank_subject_rejected` | → 422. |
| `test_qr_payload_and_png` | Payload = {session_id, qr_token}; PNG magic bytes. |
| `test_scan_unknown_session` | → 400 `invalid_qr`. |
| `test_scan_future_session_not_active` | Tomorrow → 400 `session_not_active`. |
| `test_scan_out_of_range_lat` | lat 95 → 422. |
| `test_scan_empty_qr_token` | → 422. |
| `test_selfie_missing_record_404` | Nonexistent record → 404. |
| `test_selfie_record_without_photo_404` | No selfie path → 404. |
| `test_selfie_file_missing_on_disk_404` | DB row but file deleted → 404. |
| `test_sessions_pagination` | limit/offset paging, no overlap. |
| `test_export_csv_subject_filter` | Subject filter excludes other subjects. |
| `test_export_csv_faculty_filter` | Faculty filter excludes others. |
| `test_export_csv_date_filter` | Date filter isolates the day. |
| `test_faculties_endpoint` | Distinct faculty list. |
| `test_sessions_faculty_filter` | Session list filtered by faculty. |

---

## 4. Phase → test-file mapping

| Phase | Feature | Test file(s) |
|-------|---------|--------------|
| 1 | CRUD + dashboard + CSV + v2 models | `test_api`, `test_models_v2` |
| 2 | QR sessions + geo-fenced scan + selfie + device auth | `test_api`, `test_session`, `test_geo`, `test_device_auth` |
| 3 | Verification modes + attempts | `test_verification` |
| 4 | Enrichment | `test_enrichment` |
| 5 | Anomaly scoring + audit log | `test_anomaly` |
| 6 | Admin audit cockpit | `test_audit` (records/review/attempts/log) |
| 7 | Live geofence map | `test_audit` (geofence/live) |

## 5. Gap notes (for cross-verification)

- Anomaly `implausible_speed`/`new_device`/`country_change` are unit-tested at the
  `assess()` level; only `edge_of_radius`, `reused_coordinates`, and hard-block are
  exercised through real HTTP scans (device_id/country are not supplied via HTTP).
- GeoLite2 DB presence is mocked; the suite never depends on a real `.mmdb`.
- Timestamps use an injectable `now()` so date-window logic is deterministic.
- Rate limits reset per-test, so 429 tests are repeatable.
