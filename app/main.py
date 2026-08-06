from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import admin, auth, student
from app.core.config import get_settings
from app.core.logging import setup_logging

settings = get_settings()

app = FastAPI(title="Attendance System", version="0.1.0")

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


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/{path:path}", include_in_schema=False)
def serve_page(path: str):
    filename = PAGES.get(f"/{path}")
    if filename:
        return FileResponse(BASE_DIR / "templates" / filename)
    raise HTTPException(status_code=404, detail="Not found")
