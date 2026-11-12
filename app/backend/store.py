"""JSON-based metadata stores for voices and generations.

Original recordings are never modified; derived engine representations live
in the same voice folder next to the original file.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from . import config

_lock = threading.RLock()

ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".flac"}


def _read_index(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "items" in data:
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"items": {}}


def _write_index(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


# ------------------------------------------------------------------ voices
def list_voices() -> list[dict[str, Any]]:
    with _lock:
        index = _read_index(config.VOICES_INDEX_FILE)
    items = list(index["items"].values())
    items.sort(key=lambda item: item.get("created_at", 0), reverse=True)
    return items


def get_voice(voice_id: str) -> dict[str, Any] | None:
    with _lock:
        index = _read_index(config.VOICES_INDEX_FILE)
    return index["items"].get(voice_id)


def create_voice(
    *,
    name: str,
    description: str,
    source_path: Path,
) -> dict[str, Any]:
    """Register a new voice profile. Copies the original recording into the
    voice folder under `original.<ext>`; the source file stays untouched."""
    with _lock:
        voice_id = uuid.uuid4().hex[:12]
        voice_dir = config.VOICES_DIR / voice_id
        voice_dir.mkdir(parents=True, exist_ok=True)
        original_name = f"original{source_path.suffix.lower()}"
        shutil.copy2(source_path, voice_dir / original_name)

        index = _read_index(config.VOICES_INDEX_FILE)
        record = {
            "id": voice_id,
            "name": name.strip() or f"Voice {voice_id[:6]}",
            "description": description.strip(),
            "original_file": original_name,
            "original_path": str(voice_dir / original_name),
            "created_at": time.time(),
            "engines": {},
        }
        index["items"][voice_id] = record
        _write_index(config.VOICES_INDEX_FILE, index)
        return dict(record)


def update_voice(
    voice_id: str, *, name: str | None = None, description: str | None = None
) -> dict[str, Any] | None:
    with _lock:
        index = _read_index(config.VOICES_INDEX_FILE)
        record = index["items"].get(voice_id)
        if record is None:
            return None
        if name is not None:
            record["name"] = name.strip() or record["name"]
        if description is not None:
            record["description"] = description.strip()
        _write_index(config.VOICES_INDEX_FILE, index)
        return dict(record)


def set_voice_engine_artifact(
    voice_id: str, engine_id: str, artifact: dict[str, Any]
) -> None:
    with _lock:
        index = _read_index(config.VOICES_INDEX_FILE)
        record = index["items"].get(voice_id)
        if record is None:
            raise KeyError(f"voice {voice_id} not found")
        record.setdefault("engines", {})[engine_id] = artifact
        _write_index(config.VOICES_INDEX_FILE, index)


def delete_voice(voice_id: str) -> bool:
    with _lock:
        index = _read_index(config.VOICES_INDEX_FILE)
        record = index["items"].pop(voice_id, None)
        if record is None:
            return False
        _write_index(config.VOICES_INDEX_FILE, index)
        shutil.rmtree(config.VOICES_DIR / voice_id, ignore_errors=True)
        return True


# ------------------------------------------------------------ generations
def list_generations() -> list[dict[str, Any]]:
    with _lock:
        index = _read_index(config.GENERATIONS_INDEX_FILE)
    items = list(index["items"].values())
    items.sort(key=lambda item: item.get("created_at", 0), reverse=True)
    return items


def get_generation(generation_id: str) -> dict[str, Any] | None:
    with _lock:
        index = _read_index(config.GENERATIONS_INDEX_FILE)
    return index["items"].get(generation_id)


def add_generation(
    record: dict[str, Any], generation_id: str | None = None
) -> dict[str, Any]:
    with _lock:
        generation_id = generation_id or uuid.uuid4().hex[:12]
        index = _read_index(config.GENERATIONS_INDEX_FILE)
        record = dict(record)
        record["id"] = generation_id
        record.setdefault("created_at", time.time())
        index["items"][generation_id] = record
        _write_index(config.GENERATIONS_INDEX_FILE, index)
        return record


def update_generation(
    generation_id: str, updates: dict[str, Any]
) -> dict[str, Any] | None:
    with _lock:
        index = _read_index(config.GENERATIONS_INDEX_FILE)
        record = index["items"].get(generation_id)
        if record is None:
            return None
        record.update(updates)
        _write_index(config.GENERATIONS_INDEX_FILE, index)
        return dict(record)


def rename_generation(generation_id: str, name: str) -> dict[str, Any] | None:
    return update_generation(generation_id, {"name": name.strip()})


def delete_generation(generation_id: str) -> bool:
    with _lock:
        index = _read_index(config.GENERATIONS_INDEX_FILE)
        record = index["items"].pop(generation_id, None)
        if record is None:
            return False
        _write_index(config.GENERATIONS_INDEX_FILE, index)
        generation_dir = config.GENERATIONS_DIR / generation_id
        shutil.rmtree(generation_dir, ignore_errors=True)
        return True
