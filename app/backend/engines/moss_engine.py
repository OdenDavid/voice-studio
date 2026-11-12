"""MOSS-TTS-Nano ONNX engine adapter (torch-free).

Runs the official ONNX export of MOSS-TTS-Nano (Apache-2.0) on
onnxruntime CPU. This module deliberately avoids torch/torchaudio so it can
run on Intel macOS, where modern torch wheels do not exist.

Upstream runtime logic is vendored from OpenMOSS/MOSS-TTS-Nano
(Apache-2.0, see vendor/MOSS-TTS-Nano-LICENSE.txt):
  - vendor/ort_cpu_runtime.py        (ONNX session orchestration)
  - vendor/tts_robust_normalizer_single_script.py (text robustness cleaning)
"""

from __future__ import annotations

import gc
import json
import logging
import resource
import time
import wave
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .. import audio_utils, config
from ..vendor import tts_robust_normalizer_single_script as robust_normalizer
from ..vendor.ort_cpu_runtime import OrtCpuRuntime
from .base import EngineCapabilities, EngineStatus, GenerationResult, VoiceEngine

logger = logging.getLogger(__name__)

SENTENCE_END_PUNCTUATION = set(".!?。！？；;")
CLAUSE_SPLIT_PUNCTUATION = set(",，、；;：:")
CLOSING_PUNCTUATION = set("\"'”’)]}）】》」』")
SHORT_PAUSE_SECONDS = 0.40
LONG_PAUSE_SECONDS = 0.24


def _contains_cjk(text: str) -> bool:
    return any(
        "\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf"
        or "\u3040" <= ch <= "\u30ff" or "\uac00" <= ch <= "\ud7af"
        for ch in (text or "")
    )


def _split_text_by_punctuation(text: str, punctuation: set[str]) -> list[str]:
    sentences: list[str] = []
    current_chars: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        current_chars.append(character)
        if character in punctuation:
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead] in CLOSING_PUNCTUATION:
                current_chars.append(text[lookahead])
                lookahead += 1
            sentence = "".join(current_chars).strip()
            if sentence:
                sentences.append(sentence)
            current_chars.clear()
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            index = lookahead
            continue
        index += 1
    tail = "".join(current_chars).strip()
    if tail:
        sentences.append(tail)
    return sentences


def _prepare_text_for_chunking(text: str) -> str:
    normalized_text = (text or "").strip()
    if not normalized_text:
        raise ValueError("Text prompt cannot be empty.")
    normalized_text = normalized_text.replace("\r", " ").replace("\n", " ")
    while "  " in normalized_text:
        normalized_text = normalized_text.replace("  ", " ")
    if _contains_cjk(normalized_text):
        if normalized_text[-1] not in SENTENCE_END_PUNCTUATION:
            normalized_text += "。"
        return normalized_text
    if normalized_text[:1].islower():
        normalized_text = normalized_text[:1].upper() + normalized_text[1:]
    if normalized_text[-1].isalnum():
        normalized_text += "."
    return normalized_text


def _write_wav(path: str | Path, waveform: np.ndarray, sample_rate: int) -> Path:
    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio = np.asarray(waveform, dtype=np.float32)
    if audio.ndim == 1:
        audio = audio.reshape(-1, 1)
    clipped = np.clip(audio, -1.0, 1.0)
    pcm16 = np.round(clipped * 32767.0).astype(np.int16)
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(int(pcm16.shape[1]))
        wav_file.setsampwidth(2)
        wav_file.setframerate(int(sample_rate))
        wav_file.writeframes(pcm16.tobytes())
    return output_path


def _merge_audio_channels(channel_arrays: list[np.ndarray]) -> np.ndarray:
    if not channel_arrays:
        return np.zeros((0, 1), dtype=np.float32)
    if len(channel_arrays) == 1:
        return np.asarray(channel_arrays[0], dtype=np.float32).reshape(-1, 1)
    min_length = min(int(channel.shape[0]) for channel in channel_arrays)
    trimmed = [
        np.asarray(channel[:min_length], dtype=np.float32)
        for channel in channel_arrays
    ]
    return np.stack(trimmed, axis=1)



class MossEngine(VoiceEngine):
    """VoiceEngine adapter around the MOSS-TTS-Nano ONNX runtime."""

    def __init__(self) -> None:
        self.capabilities = EngineCapabilities(
            engine_id="moss",
            display_name="MOSS-TTS-Nano (ONNX CPU)",
            voice_cloning=True,
            voice_profiles=True,
            speed_control=False,
            streaming=False,
            sample_rate=48000,
            channels=2,
        )
        self._runtime: OrtCpuRuntime | None = None
        self._model_dir: Path | None = None

    # ------------------------------------------------------------------ base
    def load_model(self) -> None:
        if self._runtime is not None:
            return
        tts_dir = config.MOSS_TTS_DIR
        codec_dir = config.MOSS_CODEC_DIR
        if not (tts_dir / "browser_poc_manifest.json").exists():
            raise RuntimeError(
                f"MOSS ONNX weights not found under {tts_dir}. "
                "Run scripts/download_models.sh first."
            )
        if not (codec_dir / "codec_browser_onnx_meta.json").exists():
            raise RuntimeError(
                f"MOSS codec weights not found under {codec_dir}. "
                "Run scripts/download_models.sh first."
            )
        model_dir = tts_dir.parent  # contains both repo folders
        logger.info(
            "Loading MOSS-TTS-Nano ONNX sessions (CPU, %d threads)...",
            config.MOSS_THREADS,
        )
        start = time.perf_counter()
        self._runtime = OrtCpuRuntime(
            model_dir=model_dir,
            thread_count=config.MOSS_THREADS,
            max_new_frames=375,
            do_sample=True,
            sample_mode="fixed",
            execution_provider="cpu",
        )
        self._model_dir = model_dir
        logger.info("MOSS ONNX sessions ready in %.1fs", time.perf_counter() - start)

    def unload_model(self) -> None:
        if self._runtime is None:
            return
        self._runtime = None
        self._model_dir = None
        gc.collect()


    # ------------------------------------------------------------ text utils
    def _encode_text(self, text: str) -> list[int]:
        sp_model = self._sentencepiece()
        return [int(t) for t in sp_model.encode(text, out_type=int)]

    def _sentencepiece(self) -> Any:
        # Created once per runtime instance and cached to avoid reloading.
        sp_model = getattr(self, "_sp_cache", None)
        if sp_model is not None:
            return sp_model
        import sentencepiece as spm

        assert self._runtime is not None
        tokenizer_relative_path = str(
            self._runtime.manifest["model_files"].get(
                "tokenizer_model", "tokenizer.model"
            )
        )
        tokenizer_path = self._runtime.resolve_manifest_relative_path(
            tokenizer_relative_path
        )
        sp_model = spm.SentencePieceProcessor(model_file=str(tokenizer_path))
        self._sp_cache = sp_model
        return sp_model

    def _normalize_text(self, text: str) -> str:
        cleaned = robust_normalizer.normalize_tts_text(text or "")
        return _prepare_text_for_chunking(cleaned)

    # ------------------------------------------------------------ voice
    def create_voice_profile(
        self, voice_id: str, reference_audio_path: str
    ) -> dict[str, Any]:
        self.load_model()
        assert self._runtime is not None
        waveform = self._load_reference_audio(reference_audio_path)
        waveform_length = int(waveform.shape[-1])
        outputs = self._runtime.sessions["codec_encode"].run(
            None,
            {
                "waveform": waveform,
                "input_lengths": np.asarray([waveform_length], dtype=np.int32),
            },
        )
        output_names = [
            o.name for o in self._runtime.sessions["codec_encode"].get_outputs()
        ]
        named_outputs = dict(zip(output_names, outputs, strict=True))
        audio_codes = np.asarray(named_outputs["audio_codes"], dtype=np.int32)
        audio_code_lengths = np.asarray(
            named_outputs["audio_code_lengths"], dtype=np.int32
        )
        code_length = int(audio_code_lengths.reshape(-1)[0])
        num_quantizers = int(
            self._runtime.codec_meta["codec_config"]["num_quantizers"]
        )
        if code_length < 12:  # ≈1 s at 12.5 frames/s — no usable prompt
            raise ValueError(
                "Could not build a usable MOSS voice profile from this "
                "recording (less than one second of speech was encoded). "
                "Upload 10–30 s of clean speech and try again."
            )
        prompt_codes: list[list[int]] = []
        for frame_index in range(code_length):
            prompt_codes.append(
                [int(audio_codes[0, frame_index, q]) for q in range(num_quantizers)]
            )
        return {
            "engine_id": "moss",
            "voice_id": voice_id,
            "prompt_audio_codes": prompt_codes,
            "num_frames": code_length,
            "num_quantizers": num_quantizers,
        }


    def _load_reference_audio(self, reference_audio_path: str | Path) -> np.ndarray:
        """Prepare a voice-cloning prompt from the user's recording.

        MOSS was trained on short (roughly 5–15 s) clean studio prompts. Long,
        quiet or heavily compressed recordings produce out-of-distribution
        prompt codes that make the model emit no frames at all (silent or
        empty output), so we trim to the most speech-dense window and
        peak-normalise before encoding.
        """
        assert self._runtime is not None
        target_sample_rate = int(
            self._runtime.codec_meta["codec_config"]["sample_rate"]
        )
        target_channels = int(self._runtime.codec_meta["codec_config"]["channels"])
        mono, _sample_rate = audio_utils.prepare_reference_audio(
            reference_audio_path,
            sample_rate=target_sample_rate,
            max_seconds=audio_utils.REFERENCE_MAX_SECONDS,
        )
        # (1, channels, samples) channel-major, like the original pipeline
        data = np.repeat(mono[:, None], target_channels, axis=1)
        return np.ascontiguousarray(data.T[None, :, :].astype(np.float32))

    # ------------------------------------------------------------ generation
    def _token_count(self, value: str) -> int:
        return len(self._encode_text(value))

    def _split_voice_clone_text(self, text: str, max_tokens: int = 75) -> list[str]:
        prepared_text = _prepare_text_for_chunking(text)
        sentence_candidates = _split_text_by_punctuation(
            prepared_text, SENTENCE_END_PUNCTUATION
        ) or [prepared_text.strip()]

        sentence_slices: list[tuple[int, str]] = []
        for sentence_text in sentence_candidates:
            normalized_sentence = sentence_text.strip()
            if not normalized_sentence:
                continue
            if self._token_count(normalized_sentence) <= max_tokens:
                sentence_slices.append(
                    (self._token_count(normalized_sentence), normalized_sentence)
                )
                continue
            clause_candidates = _split_text_by_punctuation(
                normalized_sentence, CLAUSE_SPLIT_PUNCTUATION
            )
            if len(clause_candidates) <= 1:
                clause_candidates = [normalized_sentence]
            for clause_text in clause_candidates:
                normalized_clause = clause_text.strip()
                if not normalized_clause:
                    continue
                if self._token_count(normalized_clause) <= max_tokens:
                    sentence_slices.append(
                        (self._token_count(normalized_clause), normalized_clause)
                    )
                    continue
                for piece in self._split_by_token_budget(
                    normalized_clause, max_tokens
                ):
                    piece = piece.strip()
                    if piece:
                        sentence_slices.append((self._token_count(piece), piece))

        chunks: list[str] = []
        current_chunk = ""
        current_count = 0
        for sentence_count, sentence_text in sentence_slices:
            if not current_chunk:
                current_chunk = sentence_text
                current_count = sentence_count
                continue
            if current_count + sentence_count > max_tokens:
                chunks.append(current_chunk.strip())
                current_chunk = sentence_text
                current_count = sentence_count
            else:
                current_chunk = f"{current_chunk} {sentence_text}"
                current_count = self._token_count(current_chunk)
        if current_chunk:
            chunks.append(current_chunk.strip())
        return chunks if len(chunks) > 1 else [prepared_text]

    def _split_by_token_budget(self, text: str, max_tokens: int) -> list[str]:
        remaining_text = text.strip()
        if not remaining_text:
            return []
        pieces: list[str] = []
        preferred_boundary_chars = (
            set(CLAUSE_SPLIT_PUNCTUATION) | set(SENTENCE_END_PUNCTUATION) | {" "}
        )
        while remaining_text:
            if self._token_count(remaining_text) <= max_tokens:
                pieces.append(remaining_text)
                break
            low, high = 1, len(remaining_text)
            best_prefix_length = 1
            while low <= high:
                middle = (low + high) // 2
                candidate = remaining_text[:middle].strip()
                if not candidate:
                    low = middle + 1
                    continue
                if self._token_count(candidate) <= max_tokens:
                    best_prefix_length = middle
                    low = middle + 1
                else:
                    high = middle - 1
            cut_index = best_prefix_length
            prefix = remaining_text[:best_prefix_length]
            preferred_index = -1
            scan_min = max(-1, len(prefix) - 25)
            for scan_index in range(len(prefix) - 1, scan_min, -1):
                if prefix[scan_index] in preferred_boundary_chars:
                    preferred_index = scan_index + 1
                    break
            if preferred_index > 0:
                cut_index = preferred_index
            piece = remaining_text[:cut_index].strip()
            if not piece:
                piece = remaining_text[:best_prefix_length].strip()
                cut_index = best_prefix_length
            pieces.append(piece)
            remaining_text = remaining_text[cut_index:].strip()
        return pieces

        # (1, channels, samples) channel-major, like the original pipeline

    def _decode_full_audio_safe(
        self, generated_frames: list[list[int]]
    ) -> np.ndarray:
        assert self._runtime is not None
        try:
            channel_arrays, _audio_length = self._runtime.decode_full_audio(
                generated_frames
            )
            return _merge_audio_channels(channel_arrays)
        except Exception as exc:  # pragma: no cover - fallback path
            logger.warning(
                "full codec decode failed, falling back to incremental: %s", exc
            )
            self._runtime.codec_streaming_session.reset()
            channel_count = int(
                self._runtime.codec_meta["codec_config"]["channels"]
            )
            merged_by_channel: list[list[np.ndarray]] = [
                [] for _ in range(channel_count)
            ]
            try:
                for start_index in range(0, len(generated_frames), 8):
                    frame_chunk = generated_frames[start_index : start_index + 8]
                    decoded = self._runtime.codec_streaming_session.run_frames(
                        frame_chunk
                    )
                    if decoded is None:
                        continue
                    audio, audio_length = decoded
                    if audio_length <= 0:
                        continue
                    for channel_index, channel in enumerate(
                        audio[0, :, :audio_length]
                    ):
                        merged_by_channel[channel_index].append(
                            np.asarray(channel, dtype=np.float32)
                        )
            finally:
                self._runtime.codec_streaming_session.reset()
            return _merge_audio_channels(
                [
                    np.concatenate(chunks)
                    if chunks
                    else np.zeros((0,), dtype=np.float32)
                    for chunks in merged_by_channel
                ]
            )

    def _prompt_codes_for_voice(self, voice_id: str | None) -> list[list[int]]:
        assert self._runtime is not None
        if voice_id:
            codes_path = config.VOICES_DIR / voice_id / "moss_codes.json"
            if codes_path.exists():
                return json.loads(codes_path.read_text(encoding="utf-8"))
            raise ValueError(
                f"Voice '{voice_id}' has no MOSS representation yet. "
                "Re-create the voice profile for this engine."
            )
        # Default: first builtin voice (no profile selected)
        builtin = self._runtime.list_builtin_voices()
        if not builtin:
            raise RuntimeError("No builtin voices available in the MOSS manifest.")
        return list(builtin[0]["prompt_audio_codes"])

    def generate_audio(
        self,
        *,
        text: str,
        voice_id: str | None = None,
        output_path: str,
        speed: float = 1.0,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> GenerationResult:
        del speed  # no native speed control; applied as post-processing upstream
        self.load_model()
        assert self._runtime is not None
        start = time.perf_counter()
        normalized_text = self._normalize_text(text)
        prompt_codes = self._prompt_codes_for_voice(voice_id)
        chunks = self._split_voice_clone_text(normalized_text, max_tokens=75)
        sample_rate = int(self._runtime.codec_meta["codec_config"]["sample_rate"])
        channels = int(self._runtime.codec_meta["codec_config"]["channels"])
        all_waveforms: list[np.ndarray] = []
        for chunk_index, chunk_text in enumerate(chunks):
            text_token_ids = self._encode_text(chunk_text)
            request_rows = self._runtime.build_voice_clone_request_rows(
                prompt_codes, text_token_ids
            )
            generated_frames = self._runtime.generate_audio_frames(request_rows)
            waveform = self._decode_full_audio_safe(generated_frames)
            all_waveforms.append(np.asarray(waveform, dtype=np.float32))
            if chunk_index < len(chunks) - 1:
                word_count = len([w for w in chunk_text.strip().split() if w])
                pause_seconds = (
                    SHORT_PAUSE_SECONDS if word_count <= 4 else LONG_PAUSE_SECONDS
                )
                pause_samples = max(0, int(round(sample_rate * pause_seconds)))
                if pause_samples > 0:
                    all_waveforms.append(
                        np.zeros((pause_samples, channels), dtype=np.float32)
                    )
            if progress_callback is not None:
                progress_callback(chunk_index + 1, len(chunks))
        waveform = (
            np.concatenate(all_waveforms, axis=0)
            if all_waveforms
            else np.zeros((0, channels), dtype=np.float32)
        )
        if waveform.shape[0] == 0:
            raise RuntimeError(
                "MOSS produced no audio for this voice profile. The prompt "
                "codes are likely out of distribution (very quiet, noisy or "
                "heavily compressed recording). Re-create the voice profile, "
                "or upload a cleaner 10–30 s recording."
            )
        _write_wav(output_path, waveform, sample_rate)
        elapsed = time.perf_counter() - start
        duration = waveform.shape[0] / sample_rate if sample_rate else 0.0
        return GenerationResult(
            engine_id="moss",
            audio_path=str(Path(output_path).resolve()),
            sample_rate=sample_rate,
            duration_seconds=duration,
            generation_seconds=elapsed,
            chunks=len(chunks),
        )

    # ------------------------------------------------------------ status
    def get_status(self) -> EngineStatus:
        rss_mb = int(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
        )
        return EngineStatus(
            engine_id="moss",
            loaded=self._runtime is not None,
            ready=self._runtime is not None,
            detail="ready" if self._runtime is not None else "not loaded",
            model_name="MOSS-TTS-Nano-100M-ONNX",
            memory_rss_mb=rss_mb,
        )

        return np.ascontiguousarray(data.T[None, :, :].astype(np.float32))
