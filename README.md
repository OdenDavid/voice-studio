# Local Voice Studio

A lightweight, fully local text-to-speech and voice-cloning studio for
**Intel macOS** (x86_64). Clone your own voice from a short recording, type
any text, generate natural speech on CPU, preview it and export WAV/MP3 —
no GPU, no cloud, no subscription.

## Engines

| Engine | Runtime | License | Voice cloning | Notes |
|---|---|---|---|---|
| **MOSS-TTS-Nano** (default) | ONNX Runtime 1.23.2 (CPU) | Apache-2.0 | ✅ from reference audio | 48 kHz stereo, torch-free |
| **Pocket TTS** | Standalone Rust binary (x86_64) | MIT (code) / CC-BY-4.0 (weights) | ✅ after HF terms accepted | 24 kHz mono, streaming server |

Both engines run fully offline after a one-time model download.

> Why these runtimes? PyTorch dropped Intel-Mac wheel support after v2.2.2,
> so torch-based packages (Pocket TTS pip, MOSS PyTorch, OpenVoice) cannot
> install here. This project uses the torch-free paths: the MOSS ONNX export
> and the Pocket TTS Rust binary.

## Quick start

### Direct Install (Recommended)

```bash
scripts/install.sh          # one-time: uv + venv + frontend build (user-local only)
scripts/download_models.sh  # one-time: download weights (~1.3 GB total)
scripts/start.sh            # start the app
# → open http://127.0.0.1:8200
scripts/stop.sh             # stop
```

### Docker (Optional)

```bash
docker-compose build
docker-compose run --rm voice-studio bash scripts/download_models.sh
docker-compose up -d
# → open http://localhost:8200
```

See `docs/DOCKER.md` for OrbStack vs Docker Desktop comparison and configuration.

### Pocket TTS voice cloning (one-time)

Pocket TTS weights live behind a Hugging Face gate:

1. Create a free account at https://huggingface.co
2. Accept the terms at https://huggingface.co/kyutai/pocket-tts
3. `export HF_TOKEN=hf_...` then re-run `scripts/download_models.sh`

Without this, the ungated `pocket-tts-without-voice-cloning` weights are
used — all of their `mimi.encoder.*` tensors are zero, so **every** Pocket
generation (built-in or cloned) is silent. The app detects this, reports
`voice_cloning: false` on `/api/engines` and disables the engine in the UI
instead of writing silent files. MOSS-TTS-Nano needs no account and is fully
functional out of the box.

## Workflow

1. **Voice Library** — upload a WAV/MP3/M4A recording (10–30 s of clean
   speech, 44.1/48 kHz preferred), name it. Original recordings are preserved
   untouched; the app trims each upload to the most speech-dense ≤12 s window
   and peak-normalises it before encoding.
2. **Create profile** for an engine (MOSS: encoded prompt codes; Pocket:
   exported `.safetensors`). One-click per voice per engine.
3. **Generate** — paste text, pick voice + model, optional speed (0.5–2×,
   applied with FFmpeg `atempo`), export WAV or MP3.
4. **Audio Library** — every generation is stored with text, voice, model,
   date, duration and timings. Play, rename, download, delete.

## Configuration

Environment variables (optional):

| Variable | Default | Purpose |
|---|---|---|
| `VOICE_STUDIO_HOST` / `VOICE_STUDIO_PORT` | 127.0.0.1 / 8200 | API bind address |
| `VOICE_STUDIO_DATA_DIR` | `./data` | voices, generations, metadata |
| `VOICE_STUDIO_MODELS_DIR` | `./models` | model weights |
| `VOICE_STUDIO_MOSS_THREADS` | 4 | ONNX intra-op threads |
| `VOICE_STUDIO_DEFAULT_ENGINE` | moss | default engine |
| `FFMPEG_BIN` | auto | custom ffmpeg binary |
| `HF_TOKEN` | — | Pocket TTS full weights |

No absolute user-specific paths are hardcoded; everything derives from the
project location or the variables above.

## Directories

```
app/backend/      FastAPI backend (routers, engines, storage)
app/frontend/     React + TypeScript frontend (Vite)
data/voices/      <voice-id>/original.* + engine artifacts + moss_codes.json
data/generations/ <generation-id>/audio.wav|mp3
data/meta/        voices.json, generations.json, settings.json
models/           downloaded weights (not in git — run scripts/download_models.sh)
tools/            pocket-tts binary (not in git — downloaded by the script)
reference/        optional local clone of upstream MOSS-TTS-Nano (not in git)
scripts/          install, start, stop, download_models, benchmark
```

### What is deliberately not committed

`data/`, `models/`, `tools/` and `reference/` are git-ignored:

- `data/` contains **your voice recordings**, generated audio and metadata —
  private by design.
- `models/` (~1.3 GB) and `tools/` (~30 MB) are downloaded assets.
- `reference/` is a clone of <https://github.com/OpenMOSS/MOSS-TTS-Nano> kept
  locally for attribution/reference; the runtime code actually used is
  vendored in `app/backend/vendor/` with its Apache-2.0 licence.

A fresh clone therefore needs:

```bash
scripts/install.sh
scripts/download_models.sh
scripts/start.sh
```

## Backup

Back up `data/` (voices + generations + metadata) and `models/pocket_tts/`
if you exported Pocket profiles. Everything is plain files — copy the
folders back to restore. `data/meta/*.json` are human-readable indices.

## Architecture notes

- Backend exposes a `VoiceEngine` abstraction
  (`load_model / unload_model / create_voice_profile / generate_audio /
  get_status / get_capabilities`). The frontend only talks REST and never
  touches model code — adding a new engine requires no frontend changes.
- Only one engine is loaded at a time (16 GB RAM budget); switching
  engines unloads the previous one automatically.
- Generation runs in a background job with chunk-level progress; long text
  is split at sentence boundaries (never truncated) and concatenated with
  pauses.
- MP3 export and speed adjustment use the static FFmpeg bundled with the
  `imageio-ffmpeg` pip package (no system install required).

## Troubleshooting

See `docs/TROUBLESHOOTING.md`.

## Benchmarking

See `scripts/benchmark.py` and `docs/BENCHMARKS.md` for the comparison
harness and results.

## Documentation

| Document | Contents |
|---|---|
| `docs/TROUBLESHOOTING.md` | Common errors and fixes |
| `docs/DOCKER.md` | Container deployment (OrbStack vs Docker Desktop) |
| `docs/BENCHMARKS.md` | Benchmark harness and measured results |
| `docs/VOICE_PROFILE_DIAGNOSTIC.md` | Voice-cloning diagnostics (silent/degenerate output) |
| `docs/STATUS.md` | Implementation status snapshot |

See `CONTRIBUTING.md` for development setup, engine-integration guidance and
the PR testing checklist.

## License

- **This project's code:** Apache-2.0 — see `LICENSE`.
- **Vendored MOSS-TTS-Nano runtime** (`app/backend/vendor/`): Apache-2.0 —
  original text in `app/backend/vendor/MOSS-TTS-Nano-LICENSE.txt`.
- **Pocket TTS binary:** MIT (Kyutai). Its English model weights are
  CC-BY-4.0 and are downloaded at install time — **no model weights are
  redistributed in this repository**.
- Third-party attribution: see `NOTICE`.

Voice cloning must only be used with the explicit consent of the speaker,
and in compliance with the model licences and applicable law.
