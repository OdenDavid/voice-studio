"""Local Voice Studio backend (FastAPI).

Serves the REST API and the built frontend (if present).
Run with:  scripts/start.sh   (or `uvicorn app.backend.main:app`)
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .routers import library, settings, tts, voices

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("voice-studio")

app = FastAPI(title="Local Voice Studio", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://{config.HOST}:{config.PORT}",
        "http://localhost:8200",
        "http://127.0.0.1:8200",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(voices.router)
app.include_router(tts.router)
app.include_router(library.router)
app.include_router(settings.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": "voice-studio"}


# --------------------------------------------------------------------------
# Static frontend (built assets) — served after API routes.
# --------------------------------------------------------------------------
_FRONTEND_DIST = config.PROJECT_ROOT / "app" / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=_FRONTEND_DIST / "assets"),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        candidate = _FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_DIST / "index.html")


@app.on_event("shutdown")
def shutdown() -> None:
    from .engines import unload_all

    unload_all()
