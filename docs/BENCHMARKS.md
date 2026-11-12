# Benchmarks

Harness: `scripts/benchmark.py` — same reference recording and text for
every engine; measures load time, profile-creation time, generation time
(wall clock), peak RSS, average CPU utilisation, audio duration and
real-time speedup.

```bash
.venv/bin/python scripts/benchmark.py \
  --reference /path/to/your-recording.wav \
  --text "This is a benchmark sentence. The quick brown fox jumps over the lazy dog." \
  --engines moss pocket \
  --output data/benchmarks/report.json
```

(`data/` is git-ignored, so use any local recording you own — 10–30 s of
clean speech — as the reference.)

Results land in `data/benchmarks/report.json` and are summarised here as
they are produced (see git history / file timestamps). Subjective scoring
(similarity, naturalness, pronunciation) is done by listening to the same
sentence rendered by each engine with the same reference.

## Expected characteristics (from upstream documentation)

| | MOSS-TTS-Nano | Pocket TTS |
|---|---|---|
| Params | ~100M | ~100M (English) |
| Output | 48 kHz stereo | 24 kHz mono |
| Latency | realtime-capable | ~6× realtime on modern CPUs |
| Cloning input | any clean speech audio | any clean speech audio (gated weights) |

This Mac (i7-1068NG7, 4 cores/8 threads) is slower than the M4 reference
hardware in upstream figures; measure, don't assume.
