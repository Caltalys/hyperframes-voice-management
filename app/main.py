"""FastAPI app — expose pipeline qua HTTP + SSE. Chạy:

    pip install -e ".[web]"
    uvicorn app.main:app --reload        # http://127.0.0.1:8000

Engine mặc định lấy từ config["engine"]; env VO_STUDIO_ENGINE override (fake).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .jobs import manager
from .routers import export, jobs, lines, projects, takes

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager.start()          # khởi động worker trong event loop
    yield
    await manager.stop()


app = FastAPI(title="VO Studio", version="0.0.1", lifespan=lifespan)

app.include_router(projects.router)
app.include_router(lines.router)
app.include_router(takes.router)
app.include_router(export.router)
app.include_router(jobs.router)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "vo-studio"}


# UI tĩnh (M3+) — mount cuối để không nuốt /api.
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
