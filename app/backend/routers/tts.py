"""Text-to-speech generation endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import config, jobs, service, store
from ..engines import available_engines, engine_statuses, ensure_only_engine_loaded

router = APIRouter(prefix="/api", tags=["tts"])


class GenerateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=100000)
    voice_id: str | None = None
    engine_id: str
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    export_format: str = Field(default="wav", pattern="^(wav|mp3)$")


@router.post("/generate")
def generate(request: GenerateRequest) -> dict[str, Any]:
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty.")
    if request.voice_id and store.get_voice(request.voice_id) is None:
        raise HTTPException(status_code=404, detail="Voice not found.")
    try:
        service_started = service.start_generation(
            text=request.text,
            voice_id=request.voice_id,
            engine_id=request.engine_id,
            speed=request.speed,
            export_format=request.export_format,
        )
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return service_started


@router.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"job": job}


@router.get("/engines")
def engines() -> dict[str, Any]:
    return {
        "engines": [caps.__dict__ for caps in available_engines()],
        "status": {k: v.__dict__ for k, v in engine_statuses().items()},
        "default_engine": config.DEFAULT_ENGINE,
    }


@router.post("/engines/{engine_id}/load")
def load_engine(engine_id: str) -> dict[str, Any]:
    try:
        engine = ensure_only_engine_loaded(engine_id)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        engine.load_model()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": engine.get_status().__dict__}


@router.post("/engines/{engine_id}/unload")
def unload_engine(engine_id: str) -> dict[str, Any]:
    try:
        engine = ensure_only_engine_loaded(engine_id)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    engine.unload_model()
    return {"status": engine.get_status().__dict__}


@router.get("/voices/{voice_id}/check/{engine_id}")
def voice_engine_ready(voice_id: str, engine_id: str) -> dict[str, Any]:
    record = store.get_voice(voice_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Voice not found.")
    engines_data = record.get("engines", {})
    return {
        "ready": engine_id in engines_data,
        "engines": engines_data,
    }
