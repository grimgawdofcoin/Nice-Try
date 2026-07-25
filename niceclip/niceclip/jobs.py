"""In-process job queue: one worker thread, cancellable jobs, poll-friendly
status snapshots for the web UI."""

from __future__ import annotations

import queue
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Job:
    id: str
    source: str
    settings: dict
    status: str = "queued"          # queued | running | done | error | cancelled
    stage: str = "Waiting in queue"
    progress: float = 0.0           # 0..100 overall
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    clips: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: Optional[str] = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def set_stage(self, stage: str, progress: float) -> None:
        with self._lock:
            self.stage = stage
            self.progress = round(min(100.0, max(self.progress, progress)), 1)

    def stage_progress(self, base: float, span: float) -> Callable[[float], None]:
        """Progress callback mapping a stage's 0..1 onto base..base+span."""
        def cb(fraction: float) -> None:
            with self._lock:
                self.progress = round(min(100.0, base + span * min(1.0, fraction)), 1)
        return cb

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "id": self.id,
                "source": self.source,
                "settings": self.settings,
                "status": self.status,
                "stage": self.stage,
                "progress": self.progress,
                "created_at": self.created_at,
                "finished_at": self.finished_at,
                "clips": list(self.clips),
                "warnings": list(self.warnings),
                "error": self.error,
            }


class JobManager:
    """Single worker thread — video work is CPU/IO bound, so serializing jobs
    keeps the machine responsive and progress meaningful."""

    def __init__(self, runner: Callable[[Job], None]):
        self._runner = runner
        self._jobs: dict[str, Job] = {}
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()

    def submit(self, source: str, settings: dict) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], source=source, settings=settings)
        with self._lock:
            self._jobs[job.id] = job
        self._queue.put(job.id)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job is None or job.status in ("done", "error", "cancelled"):
            return False
        job.cancel_event.set()
        if job.status == "queued":
            job.status = "cancelled"
            job.stage = "Cancelled"
            job.finished_at = time.time()
        return True

    def _loop(self) -> None:
        while True:
            job_id = self._queue.get()
            job = self.get(job_id)
            if job is None or job.cancel_event.is_set():
                continue
            job.status = "running"
            try:
                self._runner(job)
                if job.cancel_event.is_set():
                    job.status = "cancelled"
                    job.stage = "Cancelled"
                else:
                    job.status = "done"
                    job.stage = "Complete"
                    job.progress = 100.0
            except Exception as e:  # noqa: BLE001 — job boundary
                if job.cancel_event.is_set():
                    job.status = "cancelled"
                    job.stage = "Cancelled"
                else:
                    job.status = "error"
                    job.stage = "Failed"
                    job.error = f"{type(e).__name__}: {e}"
                    traceback.print_exc()
            finally:
                job.finished_at = time.time()
