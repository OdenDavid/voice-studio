"""Local Voice Studio - application configuration.

All paths are derived from this file's location so the app can be moved
around freely. Environment variables allow overriding key settings.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent.parent  # repository root

APP_DIR = PROJECT_ROOT / "app"
DATA_DIR = Path(os.environ.get("VOICE_STUDIO_DATA_DIR", PROJECT_ROOT / "data"))
MODELS_DIR = Path(os.environ.get("VOICE_STUDIO_MODELS_DIR", PROJECT_ROOT / "models"))
TOOLS_DIR = PROJECT_ROOT / "tools"

VOICES_DIR = DATA_DIR / "voices"
GENERATIONS_DIR = DATA_DIR / "generations"
META_DIR = DATA_DIR / "meta"

SETTINGS_FILE = META_DIR / "settings.json"
VOICES_INDEX_FILE = META_DIR / "voices.json"
GENERATIONS_INDEX_FILE = META_DIR / "generations.json"

# Model directories
POCKET_TTS_BIN = (
    TOOLS_DIR / "pocket-tts-3.3.0-x86_64-apple-darwin" / "pocket-tts"
)
POCKET_TTS_CONFIG_DIR = MODELS_DIR / "pocket_tts"
MOSS_ONNX_DIR = MODELS_DIR / "moss_onnx"
MOSS_TTS_DIR = MOSS_ONNX_DIR / "MOSS-TTS-Nano-100M-ONNX"
MOSS_CODEC_DIR = MOSS_ONNX_DIR / "MOSS-Audio-Tokenizer-Nano-ONNX"

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
HOST = os.environ.get("VOICE_STUDIO_HOST", "127.0.0.1")
PORT = int(os.environ.get("VOICE_STUDIO_PORT", "8200"))

# ---------------------------------------------------------------------------
# Inference defaults
# ---------------------------------------------------------------------------
DEFAULT_ENGINE = os.environ.get("VOICE_STUDIO_DEFAULT_ENGINE", "moss")
MOSS_THREADS = int(os.environ.get("VOICE_STUDIO_MOSS_THREADS", "4"))
# Pocket TTS subprocess port (used by the serve-mode adapter)
POCKET_TTS_PORT = int(os.environ.get("VOICE_STUDIO_POCKET_TTS_PORT", "8201"))


def ensure_dirs() -> None:
    for directory in (
        DATA_DIR,
        VOICES_DIR,
        GENERATIONS_DIR,
        META_DIR,
        MODELS_DIR,
        POCKET_TTS_CONFIG_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_settings(settings: dict) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8"
    )


ensure_dirs()
