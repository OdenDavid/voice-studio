# Custom Voice Profile Diagnostic Report

Date: 2026-11-11 · Engines: MOSS-TTS-Nano (ONNX) and Pocket TTS (Rust binary)

## Summary

Two independent root causes were found — one per engine:

| Engine | Root cause | Status |
|---|---|---|
| **MOSS-TTS-Nano** | Prompt codes encoded from the *full, untrimmed* 39.5 s recording (16 kHz, 24 kbps MP3) are out of distribution → model emits **zero frames** (empty/silent audio) | **Fixed** — reference is now trimmed to the most speech-dense ≤12 s window, DC-removed and peak-normalised before encoding |
| **Pocket TTS** | Installed weights are the **`pocket-tts-without-voice-cloning`** variant: all 42 `mimi.encoder.*` tensors are exactly zero. Nothing can be encoded, so every generation (built-in *and* cloned) is silent | **Detected + reported** — requires the gated full weights (`HF_TOKEN`). The app now refuses to run rather than emit silent files |

The *application pipeline* (upload → profile → generate → export) was verified
correct: re-encoding the same audio with trimming produces intelligible
speech, and the MOSS codec round-trip correlates **0.931** with the source.

## 1. Original recording inspection

`data/voices/653718631381/original.mp3` (user recording):

| Property | Value |
|---|---|
| Codec | MP3 (`mp3float`), 24 kbps — heavily compressed |
| Duration | 39.53 s |
| Sample rate | **16 000 Hz** (telephone grade; Nyquist 8 kHz) |
| Channels | 1 (mono) |
| Bit depth | n/a (lossy) |
| Loudness | mean −23.1 dBFS, peak −0.4 dBFS |
| Silence | 6.9 % near-silence, no clipping |

Decoding is correct (`soundfile` reads it as 16 kHz float32; FFmpeg agrees).
The recording is **not** silent, clipped or corrupt — but 16 kHz / 24 kbps is
far below the 48 kHz studio prompts MOSS was trained on.

Second test voice (`f9217e5cb3e1`, 9.02 s 48 kHz mono WAV, −20.5 dBFS mean)
was healthy and always produced good MOSS audio.

## 2. Model-specific preprocessing

| | MOSS-TTS-Nano | Pocket TTS |
|---|---|---|
| Input rate | 48 000 Hz | 24 000 Hz |
| Channels | 2 (mono duplicated) | 1 |
| Format | float32, channel-major `(1, C, T)` | WAV upload to `serve` |
| Resampling | `scipy.signal.resample_poly` (sinc) | inside binary (Mimi) |
| Normalisation | **none (before fix)** | none |
| Silence handling | **none (before fix)** | none |

## 3. Profile creation trace

**MOSS** — `create_voice_profile()` → `_load_reference_audio()` → codec
`encode` ONNX session → `moss_codes.json` (frames × 16 VQ codes).

- Old pipeline: whole 39.5 s encoded → **494 frames** of prompt.
- Code statistics looked normal (mean 510, σ 298, 15.9 unique/frame — same as
  built-in voices), so the corruption is not visible in the code values.
- Round-trip decode of those codes back to audio gives correlation 0.931 —
  the codes faithfully represent the recording; the *model* refuses to
  generate from that conditioning.

**Pocket** — `export-voice` produced an 18.5 MB `.safetensors` KV-cache
profile. It was built from a zeroed encoder, so the cached conditioning is
meaningless. It is not used for generation (the adapter uploads the prepared
WAV), but it explains why profile creation "succeeded" despite broken weights.

## 4. Profile retrieval during generation

Correct in both engines — the right `voice_id` reaches the right artifact
(`moss_codes.json` / `voice_wav` upload). Generation failures were purely
caused by the conditioning data described above. Full end-to-end API tests
(profile job → generate job → library → download) pass.

## 5. Controlled comparisons (same text: "Hello there. This is a short test.")

| Condition | Prompt | Duration | RMS | Voiced |
|---|---|---|---|---|
| MOSS built-in voice | — | 3.12 s | 0.144 | 51 % |
| MOSS custom, clean 9 s WAV | 112 frames | 2.40 s | 0.110 | 58 % |
| MOSS custom, 5 s / 18 s / 36 s clean | 62–450 frames | 2.2–2.7 s | 0.10–0.12 | 60 % |
| MOSS custom, personal MP3 as-is | **494 frames** | **0.00 s (empty)** | — | — |
| MOSS custom, personal MP3 first 15 s | 187 frames | 2.88 s | 0.113 | 58 % |
| MOSS custom, personal MP3 first 8 s | 100 frames | 5.12 s | 0.063 | 28 % |
| MOSS custom, personal MP3 peak-normalised | 494 frames | 1.76 s | 0.086 | 42 % |
| Pocket built-in (CLI) | — | 5.24 s | **0.0004** | ~0 % |
| Pocket custom (CLI `--voice`) | 9 s WAV | 5.24 s | **0.0004** | ~0 % |

Pocket CLI outputs are bit-different but equally silent → not a request-format
problem; the encoder itself is zeroed.

## 6. Fixes applied

1. `audio_utils.prepare_reference_audio()` — decode (FFmpeg fallback for
   M4A), mono mix, resample, DC removal, edge-silence trim, best ≤12 s
   window, peak-normalise to 0.9. Used by **both** engines.
2. MOSS `_load_reference_audio()` now uses the prepared reference; profile
   creation rejects prompts shorter than ~1 s; generation raises a clear
   error instead of writing a 0 s WAV when no frames are produced.
3. Pocket engine detects the zeroed-encoder weights
   (`weights_support_cloning`), reports `voice_cloning: false` + status
   detail, and refuses generation with an actionable error. `serve` WAV
   responses are sanitised (placeholder 2 GB headers caused 41 666 s
   "durations").
4. Frontend disables the unavailable engine and hides its profile button.

## 7. Verification after the fix

- Personal recording re-profiled: **150 frames (12.0 s)** instead of 494.
- Short text → 7.6 s of speech-like audio (RMS 0.063, spectral flatness
  0.011, ZCR 0.042 — speech, not noise).
- Previously failing long text → **12.7 s** (RMS 0.087, flatness 0.009)
  instead of 112 s of near-silence.
- Built-in voice unchanged (5.2 s, RMS 0.121, flatness 0.049).
- Pocket generation now fails fast with the HF_TOKEN instructions.

## Remaining requirement

Pocket TTS voice cloning cannot work with the ungated weights by design.
To enable it: accept the terms at <https://huggingface.co/kyutai/pocket-tts>,
`export HF_TOKEN=…`, re-run `scripts/download_models.sh`, restart the app.
The engine will then report `voice_cloning: true` automatically.
