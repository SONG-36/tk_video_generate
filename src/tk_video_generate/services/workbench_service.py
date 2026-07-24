from __future__ import annotations

import shutil
import uuid
import zipfile
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from tk_video_generate.config import AppConfig
from tk_video_generate.enums import TaskStatus
from tk_video_generate.models import VideoBatch, VideoTask
from tk_video_generate.providers.mock_provider import MockVideoProvider
from tk_video_generate.repositories.sqlite_repository import SQLiteRepository
from tk_video_generate.services.worker import TaskWorker


class WorkbenchService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.config.ensure_directories()
        self.repository = SQLiteRepository(config.database_path)
        self.provider = MockVideoProvider(config)
        self.worker = TaskWorker(config, self.repository, self.provider)
        self.repository.recover_running_tasks(now_iso())

    def start_worker(self) -> None:
        self.worker.start()

    def stop_worker(self) -> None:
        self.worker.stop()

    def new_batch_id(self) -> str:
        return "BATCH_" + datetime.now(UTC).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]

    def estimate_batch_cost(self, task_count: int, duration_seconds: int) -> float:
        return self.provider.estimate_cost(task_count, duration_seconds)

    def create_confirmed_batch(
        self,
        batch_id: str,
        batch_name: str,
        uploaded_files: list[BinaryIO],
        prompts: list[str],
        duration_seconds: int,
        aspect_ratio: str,
        concurrency_limit: int,
        confirmation: str,
        expected_confirmation: str,
    ) -> VideoBatch:
        if confirmation.strip() != expected_confirmation:
            raise ValueError(f"Enter confirmation text exactly: {expected_confirmation}")
        if duration_seconds not in {3, 5, 10}:
            raise ValueError("Duration must be 3, 5, or 10 seconds.")
        if aspect_ratio not in {"9:16", "1:1", "16:9"}:
            raise ValueError("Aspect ratio must be 9:16, 1:1, or 16:9.")
        if not 1 <= concurrency_limit <= 5:
            raise ValueError("Concurrency must be between 1 and 5.")
        if len(uploaded_files) != len(prompts):
            raise ValueError("Upload count must match non-empty prompt count.")
        if not uploaded_files:
            raise ValueError("At least one task is required.")
        if len(uploaded_files) > self.config.max_tasks_per_batch:
            raise ValueError(f"At most {self.config.max_tasks_per_batch} tasks are allowed.")

        now = now_iso()
        batch = VideoBatch(
            id=batch_id,
            name=batch_name,
            provider=self.provider.name,
            concurrency_limit=concurrency_limit,
            confirmation_text=expected_confirmation,
            total_tasks=len(uploaded_files),
            created_at=now,
        )

        tasks: list[VideoTask] = []
        upload_prompt_pairs = zip(uploaded_files, prompts, strict=True)
        for index, (uploaded_file, prompt) in enumerate(upload_prompt_pairs, start=1):
            task_id = f"{batch_id}_TASK_{index:03d}"
            image_path = self._save_upload(batch_id, task_id, uploaded_file)
            tasks.append(
                VideoTask(
                    id=task_id,
                    batch_id=batch_id,
                    name=f"Task {index:03d}",
                    image_path=str(image_path),
                    prompt=prompt,
                    provider=self.provider.name,
                    duration_seconds=duration_seconds,
                    aspect_ratio=aspect_ratio,
                    status=TaskStatus.QUEUED,
                    progress=0,
                    provider_task_id=None,
                    output_video_path=None,
                    request_json_path=None,
                    result_json_path=None,
                    retry_count=0,
                    error_code=None,
                    error_message=None,
                    created_at=now,
                    updated_at=now,
                    completed_at=None,
                )
            )

        self.repository.create_batch(batch)
        self.repository.create_tasks(tasks)
        return batch

    def create_batch_from_paths(
        self,
        batch_id: str,
        batch_name: str,
        image_paths: list[Path],
        prompts: list[str],
        duration_seconds: int,
        aspect_ratio: str,
        concurrency_limit: int,
    ) -> VideoBatch:
        uploads = [PathUpload(path) for path in image_paths]
        return self.create_confirmed_batch(
            batch_id=batch_id,
            batch_name=batch_name,
            uploaded_files=uploads,
            prompts=prompts,
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
            concurrency_limit=concurrency_limit,
            confirmation=f"CONFIRM {batch_id}",
            expected_confirmation=f"CONFIRM {batch_id}",
        )

    def list_batches(self) -> list[VideoBatch]:
        return self.repository.list_batches()

    def get_batch(self, batch_id: str) -> VideoBatch | None:
        return self.repository.get_batch(batch_id)

    def list_tasks(self, batch_id: str | None = None) -> list[VideoTask]:
        return self.repository.list_tasks(batch_id)

    def get_task(self, task_id: str) -> VideoTask | None:
        return self.repository.get_task(task_id)

    def retry_task(self, task_id: str) -> None:
        self.repository.retry_task(task_id, now_iso())

    def create_batch_zip(self, batch_id: str) -> Path | None:
        batch = self.repository.get_batch(batch_id)
        if batch is None:
            return None
        tasks = self.repository.list_tasks(batch_id)
        archive_path = self.config.archives_dir / f"{batch_id}.zip"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for task in tasks:
                for path_value in (
                    task.image_path,
                    task.output_video_path,
                    task.request_json_path,
                    task.result_json_path,
                ):
                    if not path_value:
                        continue
                    path = Path(path_value)
                    if path.exists():
                        archive.write(path, arcname=f"{task.id}/{path.name}")
        return archive_path

    def _save_upload(self, batch_id: str, task_id: str, uploaded_file: BinaryIO) -> Path:
        name = getattr(uploaded_file, "name", f"{task_id}.png")
        suffix = Path(name).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg"}:
            suffix = ".png"
        target = self.config.uploads_dir / batch_id / f"{task_id}{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as output:
            shutil.copyfileobj(uploaded_file, output)
        with suppress(AttributeError, OSError):
            uploaded_file.seek(0)
        return target


class PathUpload:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.name = path.name
        self._handle = path.open("rb")

    def read(self, size: int = -1) -> bytes:
        return self._handle.read(size)

    def seek(self, offset: int) -> int:
        return self._handle.seek(offset)

    def close(self) -> None:
        self._handle.close()


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def clone_task_with_status(task: VideoTask, status: TaskStatus) -> VideoTask:
    return replace(task, status=status)
