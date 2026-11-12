"""High-level operations: generation pipeline, voice profile creation.

This is the only layer the API routers talk to. It owns the generation
lifecycle: engine loading, chunked synthesis, WAV/MP3 export, speed
post-processing and library bookkeeping.

Inference on an engine is serialized with a global lock: ONNX sessions and
the Pocket TTS subprocess must not be driven concurrently.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from . import audio_utils, config, jobs, store
from .engines import ensure_only_engine_loaded, get_engine_safe

logger = logging.getLogger(__name__)

_inference_lock = threading.Lock()


def start_generation(
    *,
    text: str,
    voice_id: str | None,
    engine_id: str,
    speed: float = 1.0,
    export_format: str = "wav",
) -> dict[str, Any]:
    """Queue a generation job; returns the job descriptor immediately."""

    def run(job_id_inner: str, update) -> dict[str, Any]:
        generation_dir = config.GENERATIONS_DIR / job_id_inner
        generation_dir.mkdir(parents=True, exist_ok=True)
        wav_path = generation_dir / "audio.wav"
        with _inference_lock:
            engine = ensure_only_engine_loaded(engine_id)
            result = engine.generate_audio(
                text=text,
                voice_id=voice_id,
                output_path=str(wav_path),
                speed=speed,
                progress_callback=lambda done, total: update(
                    progress=(0.1 + 0.7 * done / max(1, total)),
                    message=f"Chunk {done}/{total}",
                ),
            )

            # Optional speed post-processing (no engine supports it natively).
            final_wav = wav_path
            if speed != 1.0:
                update(progress=0.85, message="Applying speed...")
                sped = generation_dir / "audio_speed.wav"
                audio_utils.apply_speed(wav_path, sped, speed)
                final_wav = sped

            # Optional MP3 export.
            mp3_path: str | None = None
            if export_format == "mp3":
                update(progress=0.9, message="Exporting MP3...")
                mp3_target = generation_dir / "audio.mp3"
                audio_utils.transcode(final_wav, mp3_target, codec="libmp3lame")
                mp3_path = str(mp3_target)

        update(progress=0.95, message="Saving to library...")
        duration = audio_utils.wav_duration_seconds(final_wav)
        record = store.add_generation(
            {
                "text": text,
                "voice_id": voice_id,
                "engine_id": engine_id,
                "speed": speed,
                "format": export_format,
                "wav_path": str(final_wav),
                "mp3_path": mp3_path,
                "duration_seconds": round(duration, 3),
                "generation_seconds": round(result.generation_seconds, 3),
                "sample_rate": result.sample_rate,
                "chunks": result.chunks,
            },
            generation_id=job_id_inner,
        )
        return record

    job_id = jobs.run_in_background(
        "generate",
        run,
        detail=f"{engine_id} · {len(text)} chars",
    )
    return {"job_id": job_id}


def create_voice_profile_for_engine(
    voice_id: str, engine_id: str
) -> dict[str, Any]:
    record = store.get_voice(voice_id)
    if record is None:
        raise KeyError(f"voice {voice_id} not found")
    with _inference_lock:
        engine = ensure_only_engine_loaded(engine_id)
        artifact = engine.create_voice_profile(
            voice_id, record["original_path"]
        )
    store.set_voice_engine_artifact(voice_id, engine_id, artifact)
    if engine_id == "moss":
        # Also persist the prompt codes next to the voice for fast loading.
        codes = artifact.get("prompt_audio_codes")
        if codes:
            import json

            (config.VOICES_DIR / voice_id / "moss_codes.json").write_text(
                json.dumps(codes), encoding="utf-8"
            )
    return artifact
