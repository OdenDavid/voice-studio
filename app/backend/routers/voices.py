"""Voice library endpoints."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .. import config, jobs, service, store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voices", tags=["voices"])

MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB


@router.get("")
def list_voices() -> dict[str, Any]:
    return {"voices": store.list_voices()}


@router.post("")
def create_voice(
    name: str = Form(...),
    description: str = Form(""),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename.")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in store.ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format '{suffix}'. Use WAV, MP3 or M4A.",
        )
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        size = 0
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="File too large.")
            tmp.write(chunk)
    try:
        record = store.create_voice(
            name=name, description=description, source_path=tmp_path
        )
    finally:
        tmp_path.unlink(missing_ok=True)
    return {"voice": record}


@router.get("/{voice_id}")
def get_voice(voice_id: str) -> dict[str, Any]:
    record = store.get_voice(voice_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Voice not found.")
    return {"voice": record}


@router.patch("/{voice_id}")
def update_voice(voice_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    record = store.update_voice(
        voice_id,
        name=payload.get("name"),
        description=payload.get("description"),
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Voice not found.")
    return {"voice": record}


@router.delete("/{voice_id}")
def delete_voice(voice_id: str) -> dict[str, Any]:
    if not store.delete_voice(voice_id):
        raise HTTPException(status_code=404, detail="Voice not found.")
    return {"ok": True}


@router.get("/{voice_id}/audio")
def voice_audio(voice_id: str) -> FileResponse:
    record = store.get_voice(voice_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Voice not found.")
    original = Path(record["original_path"])
    if not original.exists():
        raise HTTPException(status_code=404, detail="Original recording missing.")
    media_types = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".flac": "audio/flac",
    }
    media_type = media_types.get(original.suffix.lower(), "audio/wav")
    return FileResponse(original, media_type=media_type)


@router.post("/{voice_id}/profiles/{engine_id}")
def create_engine_profile(voice_id: str, engine_id: str) -> dict[str, Any]:
    record = store.get_voice(voice_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Voice not found.")

    def run(_job_id: str, update) -> dict[str, Any]:
        update(progress=0.2, message="Loading engine...")
        artifact = service.create_voice_profile_for_engine(voice_id, engine_id)
        update(progress=1.0, message="Profile created")
        return artifact

    job_id = jobs.run_in_background(
        "voice_profile", run, detail=f"{voice_id} on {engine_id}"
    )
    return {"job_id": job_id}
