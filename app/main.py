import time
from pathlib import Path

import bcrypt
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import admin, auth, employee, student
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.db.database import Base, engine
from app.models.entities import Role, User
from app.services.auth_service import AuthError
from app.services.session_service import SessionError

settings = get_settings()
setup_logging()
logger = get_logger("app")

app = FastAPI(title="Attendance System", version="0.2.0")

app.include_router(auth.router)
app.include_router(student.router)
app.include_router(employee.router)
app.include_router(admin.router)

BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

PAGES: dict[str, str] = {
    "/": "index.html",
    "/login": "login.html",
    "/admin": "admin.html",
    "/employee": "employee.html",
    "/student": "employee.html",
}


@app.middleware("http")
async def request_logging(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    if request.url.path.startswith("/api"):
        logger.info(
            "%s %s -> %s (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
    # Never cache pages or assets: stale JS on a phone after a deploy breaks
    # the camera/selfie flow and shows errors that are hard to diagnose.
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "code": "error"})


@app.exception_handler(AuthError)
async def auth_error_handler(request: Request, exc: AuthError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "code": exc.code},
    )


@app.exception_handler(SessionError)
async def session_error_handler(request: Request, exc: SessionError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "code": exc.code},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    # Flatten pydantic's array of field errors into one human-readable message
    # instead of dumping loc/msg/type structures at the user.
    for err in exc.errors():
        if err.get("type") == "value_error":
            detail = str(err.get("msg", "")).removeprefix("Value error, ").strip()
            return JSONResponse(status_code=422, content={"detail": detail, "code": "invalid_input"})
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Please check the details you entered and try again.",
            "code": "invalid_input",
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on our side. Please try again.", "code": "internal_error"},
    )


@app.on_event("startup")
def _auto_setup():
    if settings.app_env != "production":
        return
    Base.metadata.create_all(bind=engine)
    logger.info("tables ensured")
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        if db.query(User).first():
            return
        admin_pw = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode()
        db.add(User(name="System Admin", email="admin@company.com", password_hash=admin_pw, role=Role.admin))
        for name, email, pw in [
            ("Aarav Sharma", "aarav@company.com", "student123"),
            ("Priya Patel", "priya@company.com", "student123"),
            ("Rahul Verma", "rahul@company.com", "student123"),
            ("Sneha Iyer", "sneha@company.com", "student123"),
            ("Vikram Singh", "vikram@company.com", "student123"),
        ]:
            pw_hash = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
            db.add(User(name=name, email=email, password_hash=pw_hash, role=Role.student))
        db.commit()
        logger.info("seeded admin + 5 students")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/{path:path}", include_in_schema=False)
def serve_page(path: str):
    filename = PAGES.get(f"/{path}")
    if filename:
        return FileResponse(BASE_DIR / "templates" / filename)
    raise HTTPException(status_code=404, detail="Not found")
