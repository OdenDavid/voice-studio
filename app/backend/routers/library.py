"""Audio library endpoints (past generations)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .. import store

router = APIRouter(prefix="/api/library", tags=["library"])


def _resolve_download(record: dict[str, Any], requested_format: str) -> Path:
    if requested_format == "mp3" and record.get("mp3_path"):
        path = Path(record["mp3_path"])
    else:
        path = Path(record["wav_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio file missing.")
    return path


@router.get("")
def list_generations() -> dict[str, Any]:
    return {"generations": store.list_generations()}


@router.get("/{generation_id}")
def get_generation(generation_id: str) -> dict[str, Any]:
    record = store.get_generation(generation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Generation not found.")
    return {"generation": record}


@router.patch("/{generation_id}")
def rename_generation(generation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    record = store.rename_generation(generation_id, payload.get("name", ""))
    if record is None:
        raise HTTPException(status_code=404, detail="Generation not found.")
    return {"generation": record}


@router.delete("/{generation_id}")
def delete_generation(generation_id: str) -> dict[str, Any]:
    if not store.delete_generation(generation_id):
        raise HTTPException(status_code=404, detail="Generation not found.")
    return {"ok": True}


@router.get("/{generation_id}/download")
def download_generation(
    generation_id: str, format: str = "wav"
) -> FileResponse:
    record = store.get_generation(generation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Generation not found.")
    path = _resolve_download(record, format)
    media_type = "audio/mpeg" if path.suffix == ".mp3" else "audio/wav"
    return FileResponse(path, media_type=media_type, filename=path.name)
