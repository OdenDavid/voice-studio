"""Background generation jobs with progress tracking.

Inference runs in a worker thread so the API stays responsive. Job state is
kept in memory (progress) and persisted in the generations index (result).
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable

_lock = threading.RLock()
_jobs: dict[str, dict[str, Any]] = {}
MAX_JOBS = 100


def create_job(kind: str, detail: str = "") -> str:
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {
            "id": job_id,
            "kind": kind,
            "detail": detail,
            "status": "queued",  # queued | running | done | failed
            "progress": 0.0,     # 0..1
            "message": "Queued",
            "error": None,
            "result": None,
            "created_at": time.time(),
            "started_at": None,
            "finished_at": None,
        }
        _trim()
    return job_id


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def update_job(job_id: str, **fields: Any) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job:
            job.update(fields)


def run_in_background(
    kind: str,
    fn: Callable[..., Any],
    *,
    detail: str = "",
    on_done: Callable[[dict[str, Any]], None] | None = None,
) -> str:
    """Run `fn(job_id, update)` on a worker thread; returns the job id."""
    job_id = create_job(kind, detail)

    def update(progress: float | None = None, message: str | None = None) -> None:
        fields: dict[str, Any] = {}
        if progress is not None:
            fields["progress"] = max(0.0, min(1.0, float(progress)))
        if message is not None:
            fields["message"] = str(message)
        if fields:
            update_job(job_id, **fields)

    def worker() -> None:
        update_job(
            job_id, status="running", started_at=time.time(), message="Working..."
        )
        try:
            result = fn(job_id, update)
            update_job(
                job_id,
                status="done",
                progress=1.0,
                message="Finished",
                finished_at=time.time(),
                result=result,
            )
            if on_done is not None:
                on_done(result or {})
        except Exception as exc:  # noqa: BLE001
            update_job(
                job_id,
                status="failed",
                message="Failed",
                error=str(exc),
                finished_at=time.time(),
            )

    threading.Thread(target=worker, name=f"job-{job_id}", daemon=True).start()
    return job_id


def _trim() -> None:
    if len(_jobs) <= MAX_JOBS:
        return
    finished = [
        job_id
        for job_id, job in _jobs.items()
        if job["status"] in {"done", "failed"}
    ]
    finished.sort(key=lambda job_id: _jobs[job_id].get("finished_at") or 0)
    while len(_jobs) > MAX_JOBS and finished:
        _jobs.pop(finished.pop(0), None)
