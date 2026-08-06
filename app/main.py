import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import admin, auth, student
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.services.auth_service import AuthError
from app.services.session_service import SessionError

settings = get_settings()
setup_logging()
logger = get_logger("app")

app = FastAPI(title="Attendance System", version="0.2.0")

app.include_router(auth.router)
app.include_router(student.router)
app.include_router(admin.router)

BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

PAGES: dict[str, str] = {
    "/": "index.html",
    "/login": "login.html",
    "/admin": "admin.html",
    "/student": "student.html",
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
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(AuthError)
async def auth_error_handler(request: Request, exc: AuthError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(SessionError)
async def session_error_handler(request: Request, exc: SessionError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/{path:path}", include_in_schema=False)
def serve_page(path: str):
    filename = PAGES.get(f"/{path}")
    if filename:
        return FileResponse(BASE_DIR / "templates" / filename)
    raise HTTPException(status_code=404, detail="Not found")
