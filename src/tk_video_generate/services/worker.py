from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tk_video_generate.config import AppConfig
from tk_video_generate.models import VideoTask
from tk_video_generate.providers.base import ProviderError, VideoProvider
from tk_video_generate.repositories.sqlite_repository import SQLiteRepository
from tk_video_generate.services.time import now_iso


class TaskWorker:
    def __init__(
        self,
        config: AppConfig,
        repository: SQLiteRepository,
        provider: VideoProvider,
    ) -> None:
        self.config = config
        self.repository = repository
        self.provider = provider
        self.executor = ThreadPoolExecutor(max_workers=config.max_worker_threads)
        self._lock = threading.Lock()
        self._active_task_ids: set[str] = set()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.scan_errors: list[str] = []

    @property
    def scan_thread(self) -> threading.Thread | None:
        return self._thread

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="task-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self.executor.shutdown(wait=True, cancel_futures=False)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._schedule_available_tasks()
            except Exception as exc:  # pragma: no cover - defensive worker boundary
                self.scan_errors.append(str(exc))
            self._stop_event.wait(0.5)

    def _schedule_available_tasks(self) -> None:
        batches = self.repository.list_batches()
        for batch in batches:
            running = self.repository.count_running_for_batch(batch.id)
            available = max(batch.concurrency_limit - running, 0)
            for _ in range(available):
                task = self.repository.claim_next_queued_task(batch.id, now_iso())
                if task is None:
                    break
                self._submit_task(task)

    def _submit_task(self, task: VideoTask) -> None:
        with self._lock:
            if task.id in self._active_task_ids:
                return
            self._active_task_ids.add(task.id)
        future = self.executor.submit(self._process_task, task.id)
        future.add_done_callback(lambda _future: self._discard_active(task.id))

    def _discard_active(self, task_id: str) -> None:
        with self._lock:
            self._active_task_ids.discard(task_id)

    def _process_task(self, task_id: str) -> None:
        task = self.repository.get_task(task_id)
        if task is None:
            return
        output_dir = self.config.outputs_dir / task.batch_id / task.id
        request_path = output_dir / "request.json"
        result_path = output_dir / "result.json"

        try:
            time.sleep(0.05)
            result = self.provider.generate(task, output_dir)
            self.repository.mark_succeeded(
                task_id=task.id,
                provider_task_id=str(result["provider_task_id"]),
                output_video_path=Path(str(result["video_path"])),
                request_json_path=request_path,
                result_json_path=result_path,
                now=now_iso(),
            )
        except ProviderError as exc:
            self._write_failure_result(result_path, task, exc.code, exc.message)
            self.repository.mark_failed(
                task.id,
                exc.code,
                exc.message,
                request_path if request_path.exists() else None,
                result_path,
                now_iso(),
            )
        except Exception as exc:  # pragma: no cover - defensive task boundary
            self._write_failure_result(result_path, task, "UNEXPECTED_ERROR", str(exc))
            self.repository.mark_failed(
                task.id,
                "UNEXPECTED_ERROR",
                str(exc),
                request_path if request_path.exists() else None,
                result_path,
                now_iso(),
            )
        finally:
            self.repository.sync_batch_status(task.batch_id)

    def _write_failure_result(
        self,
        result_path: Path,
        task: VideoTask,
        error_code: str,
        error_message: str,
    ) -> None:
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(
                {
                    "task_id": task.id,
                    "provider": self.provider.name,
                    "status": "FAILED",
                    "error_code": error_code,
                    "error_message": error_message,
                    "completed_at": now_iso(),
                },
                ensure_ascii=True,
                indent=2,
            ),
            encoding="utf-8",
        )
