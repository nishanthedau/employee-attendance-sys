# QR-Based Attendance Management System

Secure web attendance: employees mark attendance by scanning a QR code **and taking a
selfie** from their browser. Identity comes from the authenticated session (never from
the scan), the selfie photo is validated and stored, GPS is re-verified server-side,
duplicates and QR replay are blocked, and admins get a dashboard + CSV export.

Built with **FastAPI + SQLAlchemy + MySQL** on the back and a **minimalist dark UI**
(vanilla HTML/CSS/JS, no framework) on the front.

## Quickstart

```bash
# 1. deps + environment
uv sync
cp .env.example .env   # edit DB creds if needed

# 2. create DB + tables + seed (admin + 5 demo employees)
uv run python scripts/init_db.py

# 3. run
uv run uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000

| Role  | Email            | Password   |
|-------|------------------|------------|
| Admin | admin@company.com | admin123   |
| Employee | aarav@company.com | student123 |

## Flow

1. **Admin** logs in → **New Session** (subject, faculty, date, time window, coordinates,
   radius, QR expiry) → **Show QR**.
2. **Employee** logs in → **Scan QR Code** → camera scans the QR → camera flips to a **selfie**
   capture step (preview → confirm) → browser geolocation → the selfie + coordinates are
   uploaded as `multipart/form-data` → server validates the selfie (type/size/magic bytes),
   QR token, expiry, session window, duplicate, then Haversine distance vs. session radius →
   attendance stored with the photo path.
3. **Admin** sees today's stats, sessions, history per session (with a **Selfie** button per
   record), search, filters, CSV export. **Employee** sees only the current week (Mon–Sun).

## Structure

```
attendance-system/
├── app/
│   ├── api/            # routers: auth, student, admin + deps, schemas
│   ├── core/           # config (.env), logging, rate limiting, tz helpers, selfie storage
│   ├── db/             # SQLAlchemy engine + session
│   ├── models/         # ORM entities
│   ├── services/       # auth, geo (Haversine), sessions, qr, analytics
│   ├── static/         # css/js (vanilla, Instagram-inspired)
│   ├── templates/      # login/admin/student pages
│   └── main.py         # FastAPI app + page serving
├── database/schema.sql # reference DDL
├── scripts/init_db.py  # create DB, tables (incl. selfie_path migration), seed
└── storage/            # logs, exports, selfies
```

## API

| Endpoint                              | Role    | Notes                              |
|---------------------------------------|---------|------------------------------------|
| `POST /api/auth/login`                | public  | returns bearer token               |
| `POST /api/auth/logout`               | any     | revokes token                      |
| `POST /api/admin/attendance/create`   | admin   | create session + QR token          |
| `GET  /api/admin/attendance/qr`       | admin   | QR PNG (`session_id` query)        |
| `GET  /api/admin/dashboard`           | admin   | today's stats, recent sessions/activity |
| `GET  /api/admin/sessions`            | admin   | filter `subject`, `session_date`   |
| `GET  /api/admin/attendance/history`  | admin   | per-session records (`session_id`) |
| `GET  /api/admin/export`              | admin   | CSV, filters `subject`/`session_date` |
| `GET  /api/admin/students`            | admin   | search `q`                         |
| `POST /api/admin/students`            | admin   | add employee (409 on duplicate)     |
| `DELETE /api/admin/students/{id}`     | admin   | remove employee + records           |
| `GET  /api/admin/selfie/{record_id}`  | admin   | employee selfie image (PNG/JPEG)    |
| `GET  /api/admin/settings`            | admin   | org settings (mode, radius, sheets toggle) |
| `PUT  /api/admin/settings`            | admin   | update org settings                |
| `GET  /api/admin/sheets/queue`        | admin   | pending Google Sheets sync queue   |
| `POST /api/admin/sheets/sync`         | admin   | drain the Sheets queue (optional `session_id`) |
| `POST /api/student/attendance/scan`   | student | multipart: session_id, qr_token, latitude, longitude, selfie |
| `GET  /api/student/attendance/current-week` | student | Mon–Sun this week only     |

Interactive docs at http://localhost:8000/docs

## Security

- Bearer tokens in `auth_tokens` (revocable via logout, 12h TTL); multiple concurrent sessions per user allowed
- QR replay/expired QR blocked: token single-use per session, `expires_at` checked at scan
- Duplicate prevention: unique `(student_id, session_id)` constraint + transactional check
- Session window (`date`, `start_time`, `end_time`) enforced server-side
- GPS verified with Haversine; identity from token, coordinates never trusted from client
- Selfie required with every scan: type (JPG/PNG), size (≤ 2 MB), and magic bytes validated;
  photos stored under `storage/selfies/` and served only via the admin-only `/api/admin/selfie/{id}`
- All SQL via SQLAlchemy prepared statements; role checks on every admin route
