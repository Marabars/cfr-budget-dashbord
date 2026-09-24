"""Точка входа FastAPI: статика, API, инициализация БД.

Запуск:  python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__, db
from app.routers import edit, files, operplan, registry, views

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("BUDGET_DB"):
        db.set_db_path(os.environ["BUDGET_DB"])
    db.init_db()
    yield


app = FastAPI(
    title="Бюджеты ЦФО",
    version=__version__,
    description="Контроль исполнения бюджетов центров финансовой ответственности",
    lifespan=lifespan,
)

app.include_router(views.router)
app.include_router(edit.router)
app.include_router(files.router)
app.include_router(registry.router)
app.include_router(operplan.router)


@app.middleware("http")
async def no_cache_static(request, call_next):
    """Интерфейс не кэшируем: после обновления версии браузер должен взять новые файлы."""
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".js", ".css", ".html")):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__, "db": str(db.get_db_path())}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.exception_handler(ValueError)
async def value_error_handler(request, exc: ValueError) -> JSONResponse:
    """Ошибки бизнес-правил отдаём как 422 с понятным текстом."""
    return JSONResponse(status_code=422, content={"detail": str(exc)})


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")