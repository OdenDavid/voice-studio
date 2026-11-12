# Contributing

Thanks for taking a look at Local Voice Studio. This project targets
**Intel macOS with CPU-only inference**, so contributions must keep that
constraint intact.

## Development setup

```bash
scripts/install.sh          # uv + .venv + frontend dependencies
scripts/download_models.sh  # weights (~1.3 GB) + Pocket TTS binary
scripts/start.sh            # production mode: http://127.0.0.1:8200
scripts/start.sh dev        # backend :8200 + Vite dev server :5173
```

Requires Python 3.11+, Node 18+, and a Hugging Face token only if you want
Pocket TTS voice cloning (see README).

## Ground rules

1. **No PyTorch / torchaudio.** Intel-Mac wheels do not exist for modern
   versions. Use ONNX Runtime or prebuilt binaries.
2. **Keep the engine abstraction.** The frontend must only talk REST;
   engines implement `VoiceEngine` (`app/backend/engines/base.py`).
3. **One engine loaded at a time** — 16 GB RAM budget. Respect
   `ensure_only_engine_loaded()` and the inference lock in `service.py`.
4. **Never mutate the user's upload.** `data/voices/<id>/original.*` is the
   source of truth; derived artifacts are stored beside it.
5. **Keep engines separate.** Prompt preprocessing and voice
   representations are engine-specific — do not share formats across them.

## Adding a new engine

1. Create `app/backend/engines/<name>_engine.py` implementing
   `VoiceEngine` (load/unload, `create_voice_profile`, `generate_audio`,
   `get_status`).
2. Register it in `app/backend/engines/registry.py`.
3. Add its license and attribution to `NOTICE` and the README table.
4. No frontend changes should be necessary; verify `/api/engines` exposes
   correct capabilities.

## Frontend

- React 19 + TypeScript + Vite (`app/frontend`), strict types.
- `npm run build` writes `app/frontend/dist/` (git-ignored; FastAPI serves
  it in production mode).
- Keep API shapes in `app/frontend/src/api.ts` in sync with the routers.

## Testing checklist

Before opening a PR, verify manually:

- `curl http://127.0.0.1:8200/api/health` returns `{"status":"ok"}`
- upload a recording → create a profile → generate → download WAV and MP3
- built-in voice generation still works for both engines
- `scripts/benchmark.py` runs on your reference recording
- no new files appear under `data/`, `models/` or `tools/` in `git status`

## Commits and pull requests

- Keep commits focused; explain the *why* in the message body.
- Include measured numbers (timings, RMS, durations) when changing audio
  handling — this project prefers evidence over assumptions.
- Describe hardware when reporting performance (CPU model, RAM).

## Licensing of contributions

By contributing you agree that your code is licensed under the project's
Apache-2.0 licence (see `LICENSE`). Do not add model weights, personal
voice recordings, or other binary assets to the repository.
