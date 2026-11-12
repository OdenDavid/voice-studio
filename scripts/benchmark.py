#!/usr/bin/env python3
"""Benchmark harness for Local Voice Studio engines.

For each engine: load model, create voice profile from a reference recording,
generate a fixed text, and measure wall time, peak RSS and CPU utilisation.

Usage:
  .venv/bin/python scripts/benchmark.py \
      --reference path/to/reference.wav \
      --text "The benchmark sentence." \
      --output data/benchmarks/report.json
"""

from __future__ import annotations

import argparse
import json
import resource
import subprocess
import threading
import time
from pathlib import Path

import sys

try:
    import psutil  # optional; CPU sampling skipped if unavailable
except ImportError:  # pragma: no cover
    psutil = None

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from backend.engines.registry import get_engine, unload_all  # noqa: E402


class CpuSampler(threading.Thread):
    """Samples process CPU usage during a benchmark run."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.samples: list[float] = []
        self._stop = threading.Event()

    def run(self) -> None:
        proc = psutil.Process() if psutil is not None else None
        while not self._stop.is_set():
            if proc is not None:
                try:
                    self.samples.append(proc.cpu_percent(interval=0.2))
                except Exception:  # noqa: BLE001
                    pass
            else:
                time.sleep(0.2)
        # psutil cpu_percent(interval=None) returns since last call; fine here.

    def stop(self) -> None:
        self._stop.set()

    def average(self) -> float | None:
        if not self.samples:
            return None
        return sum(self.samples) / len(self.samples)


def peak_rss_mb() -> int:
    return int(
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
    )


def benchmark_engine(
    engine_id: str,
    reference_audio: str,
    text: str,
) -> dict:
    engine = get_engine(engine_id)
    result: dict = {"engine": engine_id, "ok": False}
    try:
        # 1. Model load
        sampler = CpuSampler()
        sampler.start()
        start = time.perf_counter()
        engine.load_model()
        result["load_seconds"] = round(time.perf_counter() - start, 2)
        result["rss_after_load_mb"] = peak_rss_mb()

        # 2. Voice profile from reference
        start = time.perf_counter()
        try:
            engine.create_voice_profile("benchmark_voice", reference_audio)
            result["profile_seconds"] = round(time.perf_counter() - start, 2)
            result["profile_ok"] = True
        except Exception as exc:  # noqa: BLE001
            result["profile_seconds"] = round(time.perf_counter() - start, 2)
            result["profile_ok"] = False
            result["profile_error"] = str(exc)

        # 3. Generation
        import tempfile

        out = Path(tempfile.mkdtemp()) / "bench.wav"
        start = time.perf_counter()
        generation = engine.generate_audio(
            text=text, voice_id="benchmark_voice", output_path=str(out)
        )
        result["generate_seconds"] = round(time.perf_counter() - start, 2)
        result["audio_seconds"] = round(generation.duration_seconds, 2)
        result["speedup"] = round(
            generation.duration_seconds / max(generation.generation_seconds, 1e-6),
            2,
        )
        result["rss_after_generate_mb"] = peak_rss_mb()
        result["chunks"] = generation.chunks
        result["audio_path"] = str(out)
        result["ok"] = True
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
    finally:
        sampler.stop()
        result["avg_cpu_percent"] = (
            round(sampler.average(), 1) if sampler.average() is not None else None
        )
        unload_all()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", required=True, help="Reference recording")
    parser.add_argument(
        "--text",
        default=(
            "This is a benchmark sentence. The quick brown fox jumps over "
            "the lazy dog. Numbers like forty two and dates like nineteen "
            "ninety nine should be pronounced correctly."
        ),
        help="Text to synthesize",
    )
    parser.add_argument(
        "--engines", nargs="+", default=["moss", "pocket"]
    )
    parser.add_argument("--output", default="data/benchmarks/report.json")
    args = parser.parse_args()

    results = []
    for engine_id in args.engines:
        print(f"\n=== Benchmarking {engine_id} ===", flush=True)
        result = benchmark_engine(engine_id, args.reference, args.text)
        results.append(result)
        print(json.dumps(result, indent=2), flush=True)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {"text": args.text, "reference": args.reference, "results": results},
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nReport written to {output_path}")


if __name__ == "__main__":
    main()
