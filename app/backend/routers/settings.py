"""Settings and system info endpoints."""

from __future__ import annotations

import platform
import subprocess
from typing import Any

from fastapi import APIRouter

from .. import config

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def get_settings() -> dict[str, Any]:
    return {"settings": config.load_settings()}


@router.put("")
def update_settings(payload: dict[str, Any]) -> dict[str, Any]:
    settings = config.load_settings()
    for key in ("default_engine", "default_speed", "default_export_format"):
        if key in payload:
            settings[key] = payload[key]
    config.save_settings(settings)
    return {"settings": settings}


@router.get("/system")
def system_info() -> dict[str, Any]:
    memory = {}
    try:
        proc = subprocess.run(
            ["vm_stat"], capture_output=True, text=True, timeout=10
        )
        for line in proc.stdout.splitlines():
            if "page size" in line:
                page_size = int(line.split()[-1])
                memory["page_size_bytes"] = page_size
            elif "Pages free" in line:
                memory["free_mb"] = int(line.split()[-2].rstrip(".")) * page_size // (1024 * 1024)
            elif "Pages active" in line:
                memory["active_mb"] = int(line.split()[-2].rstrip(".")) * page_size // (1024 * 1024)
    except Exception:  # noqa: BLE001
        memory = {}
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "memory": memory,
        "data_dir": str(config.DATA_DIR),
        "models_dir": str(config.MODELS_DIR),
    }
