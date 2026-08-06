# QR-Based Attendance Management System

Secure web attendance: students mark attendance by scanning a QR code. Identity comes from
the authenticated session (never from the scan), GPS is re-verified server-side, duplicates and
QR replay are blocked, and admins get a dashboard + CSV export.

Built with **FastAPI + SQLAlchemy + MySQL** on the back and a **minimalist dark UI**
(vanilla HTML/CSS/JS, no framework) on the front.

## Quickstart

```bash
# 1. deps + environment
uv sync
cp .env.example .env   # edit DB creds if needed

# 2. create DB + tables + seed (admin + 5 demo students)
uv run python scripts/init_db.py

# 3. run
uv run uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000

| Role  | Email            | Password   |
|-------|------------------|------------|
| Admin | admin@campus.edu | admin123   |
| Student | aarav@campus.edu | student123 |

## Flow

1. **Admin** logs in → **New Session** (subject, faculty, date, time window, coordinates,
   radius, QR expiry) → **Show QR**.
2. **Student** logs in → **Scan QR Code** → camera scans the QR → browser geolocation →
   server validates QR token, expiry, session window, duplicate, then Haversine distance
   vs. session radius → attendance stored.
3. **Admin** sees today's stats, sessions, history per session, search, filters, CSV export.
   **Student** sees only the current week (Mon–Sun).

## Structure

```
attendance-system/
├── app/
│   ├── api/            # routers: auth, student, admin + deps, schemas
│   ├── core/           # config (.env), logging
│   ├── db/             # SQLAlchemy engine + session
│   ├── models/         # ORM entities
│   ├── services/       # auth, geo (Haversine), sessions, qr, analytics
│   ├── static/         # css/js (vanilla, Instagram-inspired)
│   ├── templates/      # login/admin/student pages
│   └── main.py         # FastAPI app + page serving
├── database/schema.sql # reference DDL
├── scripts/init_db.py  # create DB, tables, seed
└── storage/            # logs, exports
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
| `POST /api/student/attendance/scan`   | student | QR + GPS validation                |
| `GET  /api/student/attendance/current-week` | student | Mon–Sun this week only     |

Interactive docs at http://localhost:8000/docs

## Security

- Bearer tokens in `auth_tokens` (revocable via logout, 12h TTL); multiple concurrent sessions per user allowed
- QR replay/expired QR blocked: token single-use per session, `expires_at` checked at scan
- Duplicate prevention: unique `(student_id, session_id)` constraint + transactional check
- Session window (`date`, `start_time`, `end_time`) enforced server-side
- GPS verified with Haversine; identity from token, coordinates never trusted from client
- All SQL via SQLAlchemy prepared statements; role checks on every admin route
