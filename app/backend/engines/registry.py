"""Engine registry and active-engine management.

Only one engine may hold a model in memory at a time (16 GB budget).
Switching engines unloads the previous one first.
"""

from __future__ import annotations

import threading
from typing import Any

from .base import EngineCapabilities, EngineStatus, VoiceEngine
from .moss_engine import MossEngine
from .pocket_tts_engine import PocketTtsEngine

_lock = threading.RLock()

_ENGINES: dict[str, VoiceEngine] = {
    "moss": MossEngine(),
    "pocket": PocketTtsEngine(),
}


def available_engines() -> list[EngineCapabilities]:
    return [engine.get_capabilities() for engine in _ENGINES.values()]


def get_engine(engine_id: str) -> VoiceEngine:
    engine = _ENGINES.get(engine_id)
    if engine is None:
        raise KeyError(f"unknown engine: {engine_id}")
    return engine


def get_engine_safe(engine_id: str | None) -> VoiceEngine:
    from . import config

    resolved = engine_id or config.DEFAULT_ENGINE
    return get_engine(resolved)


def unload_all() -> None:
    for engine in _ENGINES.values():
        engine.unload_model()


def engine_statuses() -> dict[str, EngineStatus]:
    return {engine_id: engine.get_status() for engine_id, engine in _ENGINES.items()}


def ensure_only_engine_loaded(engine_id: str) -> VoiceEngine:
    """Unload every engine except the requested one, then return it."""
    with _lock:
        engine = get_engine(engine_id)
        for other_id, other in _ENGINES.items():
            if other_id != engine_id:
                other.unload_model()
        return engine
