"""Common engine interface shared by all inference providers.

The frontend talks only to this abstraction; adding a new engine never
requires frontend changes.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EngineCapabilities:
    engine_id: str
    display_name: str
    voice_cloning: bool = False
    voice_profiles: bool = False  # supports persistent voice profile files
    speed_control: bool = False    # native speed control
    streaming: bool = False
    sample_rate: int = 24000
    channels: int = 1
    max_text_chars: int = 0  # 0 = no hard limit (app chunks as needed)
    licensed_models: list[str] = field(default_factory=list)


@dataclass
class EngineStatus:
    engine_id: str
    loaded: bool
    ready: bool
    detail: str = ""
    model_name: str = ""
    memory_rss_mb: int = 0


@dataclass
class GenerationResult:
    engine_id: str
    audio_path: str
    sample_rate: int
    duration_seconds: float
    generation_seconds: float
    chunks: int = 1
    extra: dict[str, Any] = field(default_factory=dict)


class VoiceEngine(abc.ABC):
    """Abstract interface for TTS engines."""

    capabilities: EngineCapabilities

    @abc.abstractmethod
    def load_model(self) -> None:
        """Load model weights into memory (idempotent)."""

    @abc.abstractmethod
    def unload_model(self) -> None:
        """Free model memory."""

    @abc.abstractmethod
    def create_voice_profile(
        self, voice_id: str, reference_audio_path: str
    ) -> dict[str, Any]:
        """Create an engine-specific voice representation from reference audio.

        The original recording is preserved by the voice library; this only
        produces derived artifacts stored next to the voice profile.
        """

    @abc.abstractmethod
    def generate_audio(
        self,
        *,
        text: str,
        voice_id: str | None = None,
        output_path: str,
        speed: float = 1.0,
        progress_callback: Any = None,
    ) -> GenerationResult:
        """Synthesize speech for `text` using `voice_id` (a voice library id)."""

    @abc.abstractmethod
    def get_status(self) -> EngineStatus:
        """Report load state and resource usage."""

    def get_capabilities(self) -> EngineCapabilities:
        return self.capabilities

    def supported_voice_kinds(self) -> list[str]:
        return ["profile"]
