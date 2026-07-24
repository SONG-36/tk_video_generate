from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from tk_video_generate.config import AppConfig
from tk_video_generate.enums import TaskStatus
from tk_video_generate.models import VideoTask
from tk_video_generate.providers.base import ProviderError, ProviderPollResult, VideoProvider
from tk_video_generate.providers.factory import create_provider
from tk_video_generate.repositories.sqlite_repository import SQLiteRepository
from tk_video_generate.services.time import now_iso


class TaskWorker:
    def __init__(
        self,
        config: AppConfig,
        repository: SQLiteRepository,
        provider: VideoProvider | None = None,
    ) -> None:
        self.config = config
        self.repository = repository
        self.provider_override = provider
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

    def process_poll_once(self, task_id: str) -> None:
        self._process_poll(task_id)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._schedule_available_tasks()
                self._schedule_pollable_tasks()
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
                self._submit_task(task.id, self._process_submission)

    def _schedule_pollable_tasks(self) -> None:
        for task in self.repository.list_pollable_tasks(now_iso()):
            self._submit_task(task.id, self._process_poll)

    def _submit_task(self, task_id: str, handler) -> None:
        with self._lock:
            if task_id in self._active_task_ids:
                return
            self._active_task_ids.add(task_id)
        future = self.executor.submit(handler, task_id)
        future.add_done_callback(lambda _future: self._discard_active(task_id))

    def _discard_active(self, task_id: str) -> None:
        with self._lock:
            self._active_task_ids.discard(task_id)

    def _process_submission(self, task_id: str) -> None:
        task = self.repository.get_task(task_id)
        if task is None:
            return
        provider = self._provider_for_task(task)
        output_dir = self.config.outputs_dir / task.batch_id / task.id
        request_path = output_dir / "request.json"
        submit_response_path = output_dir / "provider_submit_response.json"
        try:
            submission = provider.submit(task, output_dir)
            self._write_json(submit_response_path, submission.raw_response)
            now = now_iso()
            self.repository.mark_submitted(
                task_id=task.id,
                provider_task_id=submission.provider_task_id,
                provider_response_path=submit_response_path,
                provider_request_path=request_path,
                now=now,
                next_poll_at=self._next_poll_at(now),
            )
            if task.provider == "mock":
                self._process_poll(task.id)
        except ProviderError as exc:
            self._write_failure_result(output_dir / "result.json", task, exc.code, exc.message)
            self.repository.mark_failed(
                task.id,
                exc.code,
                exc.message,
                request_path if request_path.exists() else None,
                output_dir / "result.json",
                now_iso(),
                output_dir / "result.json",
            )
        except Exception as exc:  # pragma: no cover - defensive task boundary
            self._write_failure_result(
                output_dir / "result.json",
                task,
                "UNEXPECTED_ERROR",
                str(exc),
            )
            self.repository.mark_failed(
                task.id,
                "UNEXPECTED_ERROR",
                "Unexpected provider submission error.",
                request_path if request_path.exists() else None,
                output_dir / "result.json",
                now_iso(),
                output_dir / "result.json",
            )
        finally:
            self.repository.sync_batch_status(task.batch_id)

    def _process_poll(self, task_id: str) -> None:
        task = self.repository.get_task(task_id)
        if task is None or not task.provider_task_id:
            return
        provider = self._provider_for_task(task)
        output_dir = self.config.outputs_dir / task.batch_id / task.id
        poll_latest_path = output_dir / "provider_poll_latest.json"
        history_path = output_dir / "provider_poll_history.jsonl"
        try:
            poll_result = provider.poll(task.provider_task_id)
            self._write_json(poll_latest_path, poll_result.raw_response)
            self._append_poll_history(history_path, poll_result)
            if poll_result.status in {"queued", "running"}:
                now = now_iso()
                self.repository.mark_polling(
                    task.id,
                    poll_result.status,
                    poll_result.progress,
                    poll_latest_path,
                    now,
                    self._next_poll_at(now),
                )
                return
            if poll_result.status in {"failed", "cancelled"}:
                self.repository.mark_failed(
                    task.id,
                    poll_result.error_code or "PROVIDER_TASK_FAILED",
                    poll_result.error_message or "Provider task failed.",
                    Path(task.request_json_path) if task.request_json_path else None,
                    output_dir / "result.json",
                    now_iso(),
                    poll_latest_path,
                )
                return
            if poll_result.status != "succeeded" or not poll_result.result_url:
                self.repository.mark_failed(
                    task.id,
                    "RESULT_URL_MISSING",
                    "Provider did not return a usable result URL.",
                    Path(task.request_json_path) if task.request_json_path else None,
                    output_dir / "result.json",
                    now_iso(),
                    poll_latest_path,
                )
                return
            self._download_result(task, provider, poll_result, poll_latest_path)
        except ProviderError as exc:
            code = exc.code
            if code == "PROVIDER_TEMPORARY_ERROR":
                now = now_iso()
                self.repository.mark_polling(
                    task.id,
                    "temporary_error",
                    task.progress,
                    poll_latest_path,
                    now,
                    self._next_poll_at(now),
                )
            else:
                self.repository.mark_failed(
                    task.id,
                    code,
                    exc.message,
                    Path(task.request_json_path) if task.request_json_path else None,
                    output_dir / "result.json",
                    now_iso(),
                    poll_latest_path,
                )
        finally:
            self.repository.sync_batch_status(task.batch_id)

    def _download_result(
        self,
        task: VideoTask,
        provider: VideoProvider,
        poll_result: ProviderPollResult,
        poll_latest_path: Path,
    ) -> None:
        output_dir = self.config.outputs_dir / task.batch_id / task.id
        now = now_iso()
        self.repository.mark_downloading(
            task.id,
            poll_result.result_url or "",
            poll_result.status,
            poll_latest_path,
            now,
        )
        output_path = output_dir / "result.mp4"
        downloaded = provider.download(poll_result.result_url or "", output_path)
        ffprobe_summary = self._validate_video(downloaded)
        result_path = output_dir / "result.json"
        result = {
            "task_id": task.id,
            "provider": task.provider,
            "model": task.model,
            "provider_task_id": task.provider_task_id,
            "status": TaskStatus.SUCCEEDED.value,
            "output_path": str(downloaded),
            "submitted_at": task.submitted_at,
            "completed_at": now_iso(),
            "poll_count": task.poll_count,
            "ffprobe_summary": ffprobe_summary,
            "error": None,
        }
        self._write_json(result_path, result)
        self.repository.mark_succeeded(
            task.id,
            task.provider_task_id or "",
            downloaded,
            output_dir / "request.json",
            result_path,
            now_iso(),
        )

    def _validate_video(self, video_path: Path) -> dict[str, object]:
        if not video_path.exists() or video_path.stat().st_size == 0:
            raise ProviderError("RESULT_VALIDATION_FAILED", "Downloaded video is empty.")
        import subprocess

        completed = subprocess.run(
            [
                self.config.ffprobe_path,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,width,height,duration",
                "-of",
                "json",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise ProviderError("RESULT_VALIDATION_FAILED", "FFprobe could not parse result.")
        parsed = json.loads(completed.stdout)
        streams = parsed.get("streams") or []
        if not streams:
            raise ProviderError("RESULT_VALIDATION_FAILED", "No video stream found.")
        stream = streams[0]
        if int(stream.get("width") or 0) <= 0 or int(stream.get("height") or 0) <= 0:
            raise ProviderError("RESULT_VALIDATION_FAILED", "Invalid video dimensions.")
        return stream

    def _provider_for_task(self, task: VideoTask) -> VideoProvider:
        if self.provider_override is not None:
            return self.provider_override
        return create_provider(task.provider, self.config)

    def _next_poll_at(self, now: str) -> str:
        timestamp = datetime.fromisoformat(now)
        return (
            timestamp + timedelta(seconds=self.config.seedance_poll_interval_seconds)
        ).isoformat()

    def _append_poll_history(self, path: Path, poll_result: ProviderPollResult) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "timestamp": now_iso(),
            "provider_status": poll_result.status,
            "progress": poll_result.progress,
            "error_code": poll_result.error_code,
            "result_url_present": bool(poll_result.result_url),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")

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
                    "provider": task.provider,
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

    def _write_json(self, path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
