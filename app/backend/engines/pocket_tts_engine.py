"""Pocket TTS engine adapter (standalone Rust binary).

Pocket TTS runs as a managed `pocket-tts serve` subprocess. The binary is a
prebuilt x86_64-apple-darwin release (MIT-licensed code); model weights are
CC-BY-4.0. Voice cloning requires the gated `kyutai/pocket-tts` weights,
which need a one-time Hugging Face login (`HF_TOKEN`).

The adapter keeps the model resident in the subprocess and talks to it over
HTTP on localhost. Model weights are referenced by LOCAL paths in the
config, so no network access is needed at generation time.
"""

from __future__ import annotations

import json
import logging
import os
import struct
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .. import audio_utils, config
from .base import EngineCapabilities, EngineStatus, GenerationResult, VoiceEngine

logger = logging.getLogger(__name__)

POCKET_SAMPLE_RATE = 24000
_START_TIMEOUT_SECONDS = 300  # first start loads weights
_CLONING_CHECK_TENSOR = "mimi.encoder.model.0.conv.weight"
_FULL_WEIGHTS_HINT = (
    "The installed Pocket TTS weights are the 'without voice cloning' "
    "variant — its voice-encoder tensors are zero, so every generation "
    "(built-in or cloned) comes out silent. Accept the terms at "
    "https://huggingface.co/kyutai/pocket-tts, export HF_TOKEN, then "
    "re-run scripts/download_models.sh to fetch the full weights."
)


class PocketTtsEngine(VoiceEngine):
    """VoiceEngine adapter around the pocket-tts standalone binary."""

    def __init__(self) -> None:
        self.capabilities = EngineCapabilities(
            engine_id="pocket",
            display_name="Pocket TTS (Rust binary)",
            voice_cloning=True,
            voice_profiles=True,
            speed_control=False,
            streaming=True,
            sample_rate=POCKET_SAMPLE_RATE,
            channels=1,
        )
        self._process: subprocess.Popen | None = None
        self._base_url = f"http://127.0.0.1:{config.POCKET_TTS_PORT}"


    # ------------------------------------------------------------ process
    def _config_path(self) -> Path:
        """Local-file config (no network at runtime)."""
        return config.POCKET_TTS_CONFIG_DIR / "english_local.yaml"

    def _model_file(self) -> Path:
        return config.POCKET_TTS_CONFIG_DIR / "english" / "model.safetensors"

    def weights_support_cloning(self) -> bool:
        """True when the installed weights contain a real voice encoder.

        The ungated `pocket-tts-without-voice-cloning` release ships with all
        `mimi.encoder.*` tensors zeroed. Using them silently produces
        near-silent audio, so we detect that up front instead of generating
        minutes of noise.
        """
        model_file = self._model_file()
        if not model_file.exists():
            return False
        try:
            with model_file.open("rb") as handle:
                header_length = struct.unpack("<Q", handle.read(8))[0]
                header = json.loads(handle.read(header_length))
                info = header.get(_CLONING_CHECK_TENSOR)
                if not info:
                    return False
                start, end = info["data_offsets"]
                handle.seek(8 + header_length + start)
                raw = handle.read(min(4096, end - start))
            values = np.frombuffer(raw, dtype=np.float32)
            return bool(values.size and float(np.max(np.abs(values))) > 0.0)
        except Exception:  # noqa: BLE001 - treat unreadable as unsupported
            logger.warning("Could not inspect Pocket TTS weights", exc_info=True)
            return False

    def get_capabilities(self) -> EngineCapabilities:
        return replace(
            self.capabilities,
            voice_cloning=self.weights_support_cloning(),
            voice_profiles=self.weights_support_cloning(),
        )

    def ensure_local_weights(self) -> Path:
        model_file = self._model_file()
        tokenizer_file = (
            config.POCKET_TTS_CONFIG_DIR / "english" / "tokenizer.json"
        )
        if model_file.exists() and tokenizer_file.exists():
            return self._config_path()
        raise RuntimeError(
            "Pocket TTS weights are missing. Run scripts/download_models.sh "
            "(requires a Hugging Face token with access to kyutai/pocket-tts)."
        )

    def load_model(self) -> None:
        if self._is_healthy():
            return
        self.stop()
        binary = config.POCKET_TTS_BIN
        if not binary.exists():
            raise RuntimeError(
                f"Pocket TTS binary not found at {binary}. "
                "Run scripts/download_models.sh."
            )
        self.ensure_local_weights()
        if not self.weights_support_cloning():
            raise RuntimeError(_FULL_WEIGHTS_HINT)
        cmd = [
            str(binary),
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(config.POCKET_TTS_PORT),
            "--config",
            str(self._config_path()),
        ]
        env = os.environ.copy()
        # Offline enforcement: never download at runtime.
        env["HF_HUB_OFFLINE"] = "1"
        logger.info("Starting Pocket TTS subprocess: %s", " ".join(cmd[1:]))
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        deadline = time.time() + _START_TIMEOUT_SECONDS
        while time.time() < deadline:
            if self._process.poll() is not None:
                stderr_tail = ""
                if self._process.stderr is not None:
                    stderr_tail = self._process.stderr.read()[-2000:]
                raise RuntimeError(f"Pocket TTS server exited early: {stderr_tail}")
            if self._is_healthy():
                return
            time.sleep(0.5)
        raise RuntimeError("Pocket TTS server did not become healthy in time.")

    def unload_model(self) -> None:
        self.stop()

    def stop(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()

    def _is_healthy(self) -> bool:
        try:
            with urllib.request.urlopen(
                f"{self._base_url}/health", timeout=2
            ) as response:
                return response.status == 200
        except Exception:  # noqa: BLE001
            return False


    # ------------------------------------------------------------ voice
    def create_voice_profile(
        self, voice_id: str, reference_audio_path: str
    ) -> dict[str, Any]:
        """Export a .safetensors voice profile via the binary's export-voice."""
        self.load_model()
        voice_dir = config.VOICES_DIR / voice_id
        voice_dir.mkdir(parents=True, exist_ok=True)
        # Normalise/trim the reference the same way for every engine: short,
        # peak-normalised prompts clone far more reliably.
        prepared_path = voice_dir / "reference_24k.wav"
        try:
            mono, rate = audio_utils.prepare_reference_audio(
                reference_audio_path,
                sample_rate=POCKET_SAMPLE_RATE,
                max_seconds=audio_utils.REFERENCE_MAX_SECONDS,
            )
            audio_utils.write_pcm16_wav(prepared_path, mono, rate)
        except Exception:  # noqa: BLE001 - fall back to the original upload
            logger.warning(
                "Could not prepare reference audio; using the original file",
                exc_info=True,
            )
            prepared_path = Path(reference_audio_path)
        profile_path = voice_dir / "pocket_voice.safetensors"
        result = subprocess.run(
            [
                str(config.POCKET_TTS_BIN),
                "export-voice",
                "--config",
                str(self._config_path()),
                str(prepared_path),
                str(profile_path),
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0 or not profile_path.exists():
            raise RuntimeError(
                f"Pocket TTS export-voice failed: {result.stderr[-800:]}"
            )
        return {
            "engine_id": "pocket",
            "voice_id": voice_id,
            "profile_path": str(profile_path),
            "size_bytes": profile_path.stat().st_size,
        }


    # ------------------------------------------------------------ generation
    def generate_audio(
        self,
        *,
        text: str,
        voice_id: str | None = None,
        output_path: str,
        speed: float = 1.0,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> GenerationResult:
        del speed
        self.load_model()
        start = time.perf_counter()
        chunks = self._split_text(text)
        outputs: list[Path] = []
        for index, chunk in enumerate(chunks):
            chunk_path = Path(output_path).with_suffix(f".part{index}.wav")
            self._request_tts(chunk, voice_id, chunk_path)
            outputs.append(chunk_path)
            if progress_callback is not None:
                progress_callback(index + 1, len(chunks))
        if len(outputs) == 1:
            Path(outputs[0]).replace(output_path)
        else:
            self._concat_wavs(outputs, Path(output_path))
            for chunk_path in outputs:
                chunk_path.unlink(missing_ok=True)
        elapsed = time.perf_counter() - start
        duration = audio_utils.wav_duration_seconds(output_path)
        return GenerationResult(
            engine_id="pocket",
            audio_path=str(Path(output_path).resolve()),
            sample_rate=POCKET_SAMPLE_RATE,
            duration_seconds=duration,
            generation_seconds=elapsed,
            chunks=len(chunks),
        )

    def _request_tts(self, text: str, voice_id: str | None, dest: Path) -> None:
        """POST /tts with the voice reference as multipart upload."""
        boundary = "----voice-studio-boundary"
        lines: list[bytes] = []
        lines.append(f"--{boundary}\r\n".encode())
        lines.append(b'Content-Disposition: form-data; name="text"\r\n\r\n')
        lines.append(text.encode("utf-8"))
        lines.append(b"\r\n")
        reference = self._reference_audio_path(voice_id)
        if reference is not None and reference.exists():
            content = reference.read_bytes()
            filename = reference.name
            lines.append(f"--{boundary}\r\n".encode())
            lines.append(
                (
                    f'Content-Disposition: form-data; name="voice_wav"; '
                    f'filename="{filename}"\r\n'
                    f"Content-Type: audio/wav\r\n\r\n"
                ).encode()
            )
            lines.append(content)
            lines.append(b"\r\n")
        lines.append(f"--{boundary}--\r\n".encode())
        body = b"".join(lines)
        request = urllib.request.Request(
            f"{self._base_url}/tts",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=1800) as response:
                data = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(
                f"Pocket TTS /tts failed ({exc.code}): {detail}"
            ) from exc
        if not data:
            raise RuntimeError("Pocket TTS returned empty audio.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        self._sanitize_wav(dest)

    @staticmethod
    def _sanitize_wav(path: Path) -> None:
        """Repair RIFF/data sizes when the server streams a placeholder header.

        `pocket-tts serve` sometimes writes 2 GB placeholder sizes, which makes
        every WAV reader report absurd durations.
        """
        try:
            data = path.read_bytes()
        except OSError:
            return
        if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            return
        data_index = data.find(b"data")
        if data_index < 0:
            return
        declared = struct.unpack("<I", data[data_index + 4 : data_index + 8])[0]
        actual = len(data) - (data_index + 8)
        if declared == actual and struct.unpack("<I", data[4:8])[0] == len(data) - 8:
            return
        patched = bytearray(data)
        struct.pack_into("<I", patched, 4, len(data) - 8)
        struct.pack_into("<I", patched, data_index + 4, actual)
        path.write_bytes(bytes(patched))
        logger.info(
            "Patched WAV header of %s (declared %d bytes, actual %d)",
            path.name, declared, actual,
        )

    def _reference_audio_path(self, voice_id: str | None) -> Path | None:
        if not voice_id:
            return None
        voice_dir = config.VOICES_DIR / voice_id
        prepared = voice_dir / "reference_24k.wav"
        if prepared.exists():
            return prepared
        return next(voice_dir.glob("original.*"), None)

    # ------------------------------------------------------------ text
    def _split_text(self, text: str, max_chars: int = 400) -> list[str]:
        cleaned = " ".join((text or "").replace("\r", " ").split("\n")).strip()
        if not cleaned:
            raise ValueError("Text prompt cannot be empty.")
        if len(cleaned) <= max_chars:
            return [cleaned]
        pieces: list[str] = []
        current = ""
        for sentence in _split_sentences(cleaned):
            if len(current) + len(sentence) + 1 > max_chars and current:
                pieces.append(current.strip())
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            pieces.append(current.strip())
        return pieces

    @staticmethod
    def _concat_wavs(parts: list[Path], dest: Path) -> None:
        import wave

        import numpy as np

        frames: list[np.ndarray] = []
        sample_rate: int | None = None
        channels: int | None = None
        for part in parts:
            with wave.open(str(part), "rb") as wav_file:
                sample_rate = sample_rate or wav_file.getframerate()
                channels = channels or wav_file.getnchannels()
                data = np.frombuffer(
                    wav_file.readframes(wav_file.getnframes()), dtype=np.int16
                )
                frames.append(data)
        merged = np.concatenate(frames).astype(np.int16)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(dest), "wb") as wav_file:
            wav_file.setnchannels(channels or 1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate or POCKET_SAMPLE_RATE)
            wav_file.writeframes(merged.tobytes())

    # ------------------------------------------------------------ status
    def get_status(self) -> EngineStatus:
        healthy = self._is_healthy()
        supports_cloning = self.weights_support_cloning()
        if self._model_file().exists() and not supports_cloning:
            detail = "weights are the no-cloning variant (would be silent)"
        else:
            detail = "serving" if healthy else "not running"
        return EngineStatus(
            engine_id="pocket",
            loaded=self._process is not None and self._process.poll() is None,
            ready=healthy and supports_cloning,
            detail=detail,
            model_name="pocket-tts-3.3.0-x86_64 (english)",
            memory_rss_mb=0,  # lives in the subprocess
        )


def _split_sentences(text: str) -> list[str]:
    import re

    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [part for part in parts if part.strip()]
