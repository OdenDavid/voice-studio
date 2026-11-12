"""Audio helpers: ffmpeg discovery, transcoding, speed, durations.

FFmpeg is resolved from (in order):
  1. $FFMPEG_BIN environment variable
  2. the static binary bundled with the `imageio-ffmpeg` pip package
  3. `ffmpeg` on PATH

Reference-audio preparation lives here too: `prepare_reference_audio()`
decodes any supported upload, mixes to mono, resamples, trims leading and
trailing silence, keeps the highest-energy window (default <= 12 s) and
peak-normalizes. Both engines use it — short prompts are what the models
were trained on, and long/untrimmed/low-gain recordings make MOSS produce
empty or degenerate generations.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

_ffmpeg_path: str | None = None

# Voice-cloning reference preparation defaults.
REFERENCE_MAX_SECONDS = 12.0
REFERENCE_TARGET_PEAK = 0.9
REFERENCE_MIN_SECONDS = 2.0
_SILENCE_FLOOR_RATIO = 0.0056  # ≈ -45 dBFS relative to the recording peak


def find_ffmpeg() -> str:
    global _ffmpeg_path
    if _ffmpeg_path is not None:
        return _ffmpeg_path
    candidates: list[str] = []
    env_bin = os.environ.get("FFMPEG_BIN")
    if env_bin:
        candidates.append(env_bin)
    try:
        import imageio_ffmpeg

        candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:  # noqa: BLE001
        pass
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        candidates.append(system_ffmpeg)
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            _ffmpeg_path = candidate
            return candidate
    raise RuntimeError(
        "FFmpeg not found. Install it (e.g. `uv pip install imageio-ffmpeg` "
        "inside the project venv) or set FFMPEG_BIN."
    )


def wav_duration_seconds(path: str | Path) -> float:
    with wave.open(str(path), "rb") as wav_file:
        frames = wav_file.getnframes()
        rate = wav_file.getframerate()
    return frames / rate if rate else 0.0


def decode_audio_file(source: str | Path) -> tuple[np.ndarray, int]:
    """Decode any audio file to mono float32 samples + sample rate.

    Uses soundfile first; falls back to the bundled FFmpeg for formats
    libsndfile cannot read (M4A/AAC).
    """
    import soundfile as sf

    path = Path(source).expanduser().resolve()
    try:
        data, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception:  # noqa: BLE001 - fall back to ffmpeg decoding
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            proc = subprocess.run(
                [
                    find_ffmpeg(), "-y", "-i", str(path),
                    "-ac", "1", "-ar", "48000", str(tmp_path),
                ],
                capture_output=True, text=True, timeout=300,
            )
            if proc.returncode != 0 or not tmp_path.exists():
                raise RuntimeError(
                    f"Could not decode audio '{path.name}': {proc.stderr[-300:]}"
                ) from None
            data, sample_rate = sf.read(
                str(tmp_path), dtype="float32", always_2d=True
            )
        finally:
            tmp_path.unlink(missing_ok=True)
    mono = np.asarray(data.mean(axis=1), dtype=np.float32)
    return mono, int(sample_rate)


def prepare_reference_audio(
    source: str | Path,
    *,
    sample_rate: int = 48000,
    max_seconds: float = REFERENCE_MAX_SECONDS,
    peak: float = REFERENCE_TARGET_PEAK,
) -> tuple[np.ndarray, int]:
    """Return a clean voice-cloning reference: mono float32 at `sample_rate`.

    Steps: mixdown, resample, DC removal, edge-silence trim, highest-energy
    window selection (<= max_seconds), peak normalisation.
    """
    import scipy.signal

    mono, source_rate = decode_audio_file(source)
    if mono.size == 0:
        raise ValueError("Reference audio is empty.")
    if source_rate != sample_rate:
        gcd = int(np.gcd(source_rate, sample_rate))
        mono = scipy.signal.resample_poly(
            mono, sample_rate // gcd, source_rate // gcd
        ).astype(np.float32, copy=False)
    mono = mono - float(np.mean(mono))  # remove DC offset

    peak_abs = float(np.max(np.abs(mono))) if mono.size else 0.0
    floor = max(1e-4, peak_abs * _SILENCE_FLOOR_RATIO)
    loud = np.flatnonzero(np.abs(mono) > floor)
    if loud.size == 0:
        raise ValueError("Reference audio appears to be silent.")
    mono = mono[int(loud[0]) : int(loud[-1]) + 1]

    max_samples = int(max_seconds * sample_rate)
    if mono.size > max_samples:
        frame = max(1, sample_rate // 2)
        frame_count = mono.size // frame
        energy = (
            np.square(mono[: frame_count * frame].reshape(frame_count, frame))
            .mean(axis=1)
        )
        window = max(1, max_samples // frame)
        cumulative = np.concatenate(([0.0], np.cumsum(energy)))
        window_sums = cumulative[window:] - cumulative[:-window]
        best_start = int(np.argmax(window_sums)) * frame
        mono = mono[best_start : best_start + max_samples]

    if mono.size < int(REFERENCE_MIN_SECONDS * sample_rate):
        raise ValueError(
            "Reference audio is too short after trimming silence "
            f"(need at least ~{REFERENCE_MIN_SECONDS:.0f} s of speech)."
        )
    current_peak = float(np.max(np.abs(mono))) or 1.0
    mono = (mono * (peak / current_peak)).astype(np.float32, copy=False)
    return np.ascontiguousarray(mono), sample_rate


def write_pcm16_wav(
    path: str | Path, mono: np.ndarray, sample_rate: int
) -> Path:
    """Write mono float32 samples as a 16-bit PCM WAV."""
    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pcm16 = np.round(np.clip(mono, -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(int(sample_rate))
        wav_file.writeframes(pcm16.tobytes())
    return output_path


def transcode(
    source: str | Path,
    dest: str | Path,
    *,
    codec: str = "libmp3lame",
    bitrate: str = "192k",
    speed: float = 1.0,
    extra_args: list[str] | None = None,
) -> Path:
    """Transcode audio via ffmpeg; optionally apply tempo (speed)."""
    source_path = Path(source).resolve()
    dest_path = Path(dest).resolve()
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [find_ffmpeg(), "-y", "-i", str(source_path)]
    if speed != 1.0:
        tempo = max(0.5, min(2.0, float(speed)))
        cmd += ["-filter:a", f"atempo={tempo:.4f}"]
    cmd += ["-codec:a", codec, "-b:a", bitrate]
    if extra_args:
        cmd += extra_args
    cmd += [str(dest_path)]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=600
    )
    if proc.returncode != 0 or not dest_path.exists():
        raise RuntimeError(
            f"ffmpeg transcode failed: {proc.stderr[-800:]}"
        )
    return dest_path


def apply_speed(source: str | Path, dest: str | Path, speed: float) -> Path:
    """Speed-adjust a WAV, preserving PCM16 WAV output."""
    return transcode(source, dest, codec="pcm_s16le", speed=speed)


def duration_seconds(path: str | Path) -> float:
    """Best-effort audio duration (WAV parsed natively, others via ffprobe-like ffmpeg)."""
    path = Path(path)
    if path.suffix.lower() == ".wav":
        try:
            return wav_duration_seconds(path)
        except Exception:  # noqa: BLE001
            pass
    ffmpeg = find_ffmpeg()
    ffprobe = str(Path(ffmpeg).with_name("ffprobe"))
    probe_bin = ffprobe if Path(ffprobe).exists() else shutil.which("ffprobe")
    if probe_bin:
        proc = subprocess.run(
            [probe_bin, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=120,
        )
        if proc.returncode == 0:
            return float(proc.stdout.strip())
    # Fallback: parse ffmpeg stderr
    proc = subprocess.run(
        [ffmpeg, "-i", str(path)], capture_output=True, text=True, timeout=120
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", proc.stderr)
    if match:
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return 0.0
