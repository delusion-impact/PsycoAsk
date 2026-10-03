"""Фоновые задачи с прогрессом.

Парсинг, генерация и визуализация занимают секунды, поэтому выполняются в
отдельном потоке: UI не зависает и показывает прогресс-бар. Задачи идут
строго по одной — шаги пайплайна пишут в общие файлы, параллельный запуск
смешал бы результаты разных прогонов.
"""

from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

Progress = Callable[[float, str], None]
Work = Callable[[Progress], dict[str, Any]]

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"

MAX_LOG_LINES = 300


@dataclass
class Job:
    id: str
    kind: str
    status: str = QUEUED
    progress: float = 0.0
    message: str = "В очереди"
    log: list[str] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    created: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    finished: str | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "progress": round(self.progress, 4),
            "message": self.message,
            "log": self.log[-MAX_LOG_LINES:],
            "result": self.result,
            "error": self.error,
            "created": self.created,
            "finished": self.finished,
        }


class JobManager:
    """Очередь задач: одновременно выполняется только одна."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._gate = threading.Semaphore(1)
        self._pending = 0
        self._active: str | None = None
        self._idle = threading.Event()
        self._idle.set()

    # --- Состояние ---

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = list(self._jobs.values())
        jobs.sort(key=lambda job: (job.created, job.id), reverse=True)
        return [job.snapshot() for job in jobs[:20]]

    @property
    def active(self) -> dict[str, Any] | None:
        with self._lock:
            return self._jobs[self._active].snapshot() if self._active else None

    def wait_idle(self, timeout: float | None = None) -> bool:
        """True, если очередь опустела."""
        return self._idle.wait(timeout)

    # --- Выполнение ---

    def submit(self, kind: str, work: Work) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._jobs[job.id] = job
            self._pending += 1
            self._idle.clear()
        threading.Thread(target=self._run, args=(job, work), daemon=True).start()
        return job

    def _run(self, job: Job, work: Work) -> None:
        with self._gate:  # одна задача за раз
            with self._lock:
                self._active = job.id
                job.status = RUNNING
                job.message = "Запуск"
            try:
                job.result = work(self._progress_of(job)) or {}
                job.message = "Готово"
            except Exception as exc:  # noqa: BLE001 — ошибку показываем в UI
                job.status = FAILED
                job.error = f"{type(exc).__name__}: {exc}".strip()
                job.message = "Ошибка"
                job.log.append(f"❌ {job.error}")
                tail = traceback.format_exc(limit=3).strip().splitlines()
                if len(tail) > 1:
                    job.log.append(tail[-1])
                job.finished = datetime.now().isoformat(timespec="seconds")
            else:
                job.status = DONE
                job.progress = 1.0
                job.finished = datetime.now().isoformat(timespec="seconds")

        with self._lock:
            self._active = None
            self._pending = max(0, self._pending - 1)
            if self._pending == 0:
                self._idle.set()

    @staticmethod
    def _progress_of(job: Job) -> Progress:
        def progress(fraction: float, message: str = "") -> None:
            job.progress = max(0.0, min(1.0, float(fraction)))
            if message:
                job.message = str(message)
                job.log.append(str(message))

        return progress


JOBS = JobManager()