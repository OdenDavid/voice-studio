# Troubleshooting

## Recording requirements for voice cloning (read this first)

The clone is only as good as the recording:

- **10–30 s of clean speech**, one speaker, quiet room.
- **44.1/48 kHz WAV preferred**. High-bitrate MP3/M4A is fine.
- Avoid telephone-grade audio (16 kHz / 24 kbps) — it still works after
  preprocessing but clones noticeably worse.
- Avoid background music, echo, clipping and long silences.

The app now trims every upload to the most speech-dense ≤12 s window,
removes DC offset and peak-normalises it before encoding
(`audio_utils.prepare_reference_audio`). See
`docs/VOICE_PROFILE_DIAGNOSTIC.md` for the full investigation.

## Custom voice generates silence, squeaks or 0-second files (MOSS)

Cause: prompt codes encoded from an untrimmed / very low-quality recording
are out of distribution; the model emits no frames at all.

1. Re-create the profile for that voice (Voice Library → **Create profile**).
   Profiles made before 2026-11-11 used the raw upload.
2. If it still fails, re-record closer to the microphone and export a 48 kHz
   WAV (QuickTime: File → Export → Audio Only, or `ffmpeg -i in.m4a -ar 48000
   -ac 1 out.wav`).
3. Confirm the app raised a clear error rather than saving an empty file —
   check the generation list; a 0.00 s entry means the old code path ran.

## "ModuleNotFoundError: No module named 'numpy'" (or similar)
The venv is incomplete. Re-run:
```bash
scripts/install.sh
```

## Pocket TTS stays on "Loading TTSModel weights" forever
Its downloader can stall on slow networks. Run `scripts/download_models.sh`
(uses resumable curl with stall detection) and re-try; weights then load
from local files.

## Pocket TTS: "401 Unauthorized" or missing voice cloning
The full Pocket TTS weights are gated:
1. Sign in at https://huggingface.co
2. Accept terms at https://huggingface.co/kyutai/pocket-tts
3. `export HF_TOKEN=hf_...` and re-run `scripts/download_models.sh`

If the **ungated** `pocket-tts-without-voice-cloning` weights are installed,
all 42 `mimi.encoder.*` tensors are zero — every Pocket generation, built-in
or cloned, is silent. The app detects this and reports
"weights are the no-cloning variant (would be silent)" in `GET /api/engines`;
the engine is disabled in the UI until the full weights are present.
Verify by hand: `python -c "import sys; sys.path.insert(0,'app'); from
backend.engines.registry import _ENGINES;
print(_ENGINES['pocket'].weights_support_cloning())"` → must print `True`.

## "MOSS ONNX weights not found"
Run `scripts/download_models.sh`. Both MOSS repos are ungated.

## "FFmpeg not found"
The app prefers the static FFmpeg from the `imageio-ffmpeg` pip package:
```bash
.venv/bin/python -m pip install imageio-ffmpeg
```
or `brew install ffmpeg` (system-wide — optional) or set `FFMPEG_BIN`.

## Generation is slow on first run
The first request loads the model (~10–30 s on this machine). Subsequent
generations reuse it. Models unload when you switch engines or stop the app.

## Out of memory
Only one engine loads at a time. If macOS memory pressure is high:
- close other apps,
- set `VOICE_STUDIO_MOSS_THREADS=2` (lower thread count),
- use Pocket TTS with `--quantize`-equivalent settings (not exposed yet).

## Port already in use
```bash
VOICE_STUDIO_PORT=8205 scripts/start.sh
```
or `scripts/stop.sh` first.

## Frontend shows "Connection error"
Backend not running: `scripts/start.sh` and open http://127.0.0.1:8200.

## DNS / network errors while downloading models
The downloads are resumable. Re-run `scripts/download_models.sh` — curl
resumes from where it stopped.

## Where are my files?
`data/voices/` and `data/generations/` next to the project. See README
"Directories".
