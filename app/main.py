import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/{path:path}", include_in_schema=False)
def serve_page(path: str):
    filename = PAGES.get(f"/{path}")
    if filename:
        return FileResponse(BASE_DIR / "templates" / filename)
    raise HTTPException(status_code=404, detail="Not found")
