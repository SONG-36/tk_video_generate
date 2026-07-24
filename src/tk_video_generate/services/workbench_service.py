from __future__ import annotations

import re
import shutil
import uuid
import zipfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlparse

from PIL import Image, UnidentifiedImageError

from tk_video_generate.config import AppConfig
from tk_video_generate.enums import BatchStatus, TaskStatus
from tk_video_generate.models import VideoBatch, VideoTask
from tk_video_generate.providers.factory import create_provider
from tk_video_generate.repositories.sqlite_repository import RetryNotAllowedError, SQLiteRepository
from tk_video_generate.services.time import now_iso
from tk_video_generate.services.worker import TaskWorker

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class WorkbenchService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.config.ensure_directories()
        self.repository = SQLiteRepository(config.database_path)
        self.provider = create_provider("mock", config)
        self.worker = TaskWorker(config, self.repository)
        self.repository.recover_running_tasks(now_iso())

    def start_worker(self) -> None:
        self.worker.start()

    def stop_worker(self) -> None:
        self.worker.stop()

    def new_batch_id(self) -> str:
        return "BATCH_" + datetime.now(UTC).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]

    def estimate_batch_cost(
        self,
        task_count: int,
        duration_seconds: int,
        provider_name: str = "mock",
    ) -> float | None:
        provider = create_provider(provider_name, self.config)
        return provider.estimate_batch_cost(task_count, duration_seconds)

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
        provider_name: str = "mock",
        real_api_confirmed: bool = False,
        maximum_cost_usd: float | None = None,
        image_urls: list[str | None] | None = None,
    ) -> VideoBatch:
        if confirmation.strip() != expected_confirmation:
            raise ValueError(f"Enter confirmation text exactly: {expected_confirmation}")

        self._validate_batch_id(batch_id)
        if self.repository.get_batch(batch_id) is not None:
            raise ValueError(f"Batch {batch_id} already exists.")
        provider = create_provider(provider_name, self.config)
        self._validate_batch_inputs(
            uploaded_files=uploaded_files,
            prompts=prompts,
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
            concurrency_limit=concurrency_limit,
        )
        if provider_name != "mock":
            self._validate_real_submission(
                uploaded_files=uploaded_files,
                image_urls=image_urls,
                concurrency_limit=concurrency_limit,
                real_api_confirmed=real_api_confirmed,
                maximum_cost_usd=maximum_cost_usd,
                expected_confirmation=expected_confirmation,
            )

        now = now_iso()
        batch = VideoBatch(
            id=batch_id,
            name=batch_name,
            provider=provider.name,
            status=BatchStatus.QUEUED,
            concurrency_limit=concurrency_limit,
            confirmation_text=expected_confirmation,
            total_tasks=len(uploaded_files),
            created_at=now,
        )

        tasks: list[VideoTask] = []
        upload_prompt_pairs = zip(uploaded_files, prompts, strict=True)
        for index, (uploaded_file, prompt) in enumerate(upload_prompt_pairs, start=1):
            task_id = f"{batch_id}_TASK_{index:03d}"
            image_path = self._save_and_validate_upload(batch_id, task_id, uploaded_file)
            image_url = None
            if image_urls and image_urls[index - 1]:
                image_url = image_urls[index - 1].strip()
            tasks.append(
                VideoTask(
                    id=task_id,
                    batch_id=batch_id,
                    name=f"Task {index:03d}",
                    image_path=str(image_path),
                    image_url=image_url,
                    prompt=prompt.strip(),
                    provider=provider.name,
                    model=self.config.seedance_model if provider.name != "mock" else None,
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
                    estimated_cost=None,
                )
            )

        self.repository.create_batch(batch)
        self.repository.create_tasks(tasks)
        return self.get_batch(batch_id) or batch

    def create_batch_from_paths(
        self,
        batch_id: str,
        batch_name: str,
        image_paths: list[Path],
        prompts: list[str],
        duration_seconds: int,
        aspect_ratio: str,
        concurrency_limit: int,
        provider_name: str = "mock",
        image_urls: list[str | None] | None = None,
    ) -> VideoBatch:
        uploads = [PathUpload(path) for path in image_paths]
        try:
            is_real = provider_name != "mock"
            expected_confirmation = f"CONFIRM REAL {batch_id}" if is_real else f"CONFIRM {batch_id}"
            return self.create_confirmed_batch(
                batch_id=batch_id,
                batch_name=batch_name,
                uploaded_files=uploads,
                prompts=prompts,
                duration_seconds=duration_seconds,
                aspect_ratio=aspect_ratio,
                concurrency_limit=concurrency_limit,
                confirmation=expected_confirmation,
                expected_confirmation=expected_confirmation,
                provider_name=provider_name,
                real_api_confirmed=True,
                maximum_cost_usd=self.config.real_video_max_cost_usd,
                image_urls=image_urls,
            )
        finally:
            for upload in uploads:
                upload.close()

    def list_batches(self) -> list[VideoBatch]:
        return self.repository.list_batches()

    def get_batch(self, batch_id: str) -> VideoBatch | None:
        return self.repository.get_batch(batch_id)

    def get_batch_status(self, batch_id: str) -> BatchStatus:
        return self.repository.sync_batch_status(batch_id)

    def list_tasks(self, batch_id: str | None = None) -> list[VideoTask]:
        return self.repository.list_tasks(batch_id)

    def get_task(self, task_id: str) -> VideoTask | None:
        return self.repository.get_task(task_id)

    def retry_task(self, task_id: str) -> VideoTask:
        task = self.repository.get_task(task_id)
        if task and task.provider != "mock":
            raise RetryNotAllowedError("Real provider tasks cannot be retried automatically.")
        return self.repository.retry_task(task_id, now_iso(), self.config.max_retry_count)

    def refresh_task_status(self, task_id: str) -> None:
        self.worker.process_poll_once(task_id)

    def create_batch_zip(self, batch_id: str) -> Path | None:
        batch = self.repository.get_batch(batch_id)
        if batch is None:
            return None
        tasks = self.repository.list_tasks(batch_id)
        archive_path = self.config.archives_dir / f"{batch_id}.zip"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        storage_root = self.config.storage_dir.resolve()

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
                    if not path.exists() or not self._is_within(path, storage_root):
                        continue
                    arcname = Path(batch_id) / task.id / path.name
                    if arcname.is_absolute() or ".." in arcname.parts:
                        continue
                    archive.write(path, arcname=str(arcname))
        return archive_path

    def _validate_batch_inputs(
        self,
        uploaded_files: list[BinaryIO],
        prompts: list[str],
        duration_seconds: int,
        aspect_ratio: str,
        concurrency_limit: int,
    ) -> None:
        if duration_seconds not in {3, 5, 10}:
            raise ValueError("Duration must be 3, 5, or 10 seconds.")
        if aspect_ratio not in {"9:16", "1:1", "16:9"}:
            raise ValueError("Aspect ratio must be 9:16, 1:1, or 16:9.")
        if not 1 <= concurrency_limit <= 5:
            raise ValueError("Concurrency must be between 1 and 5.")
        if len(uploaded_files) != len(prompts):
            raise ValueError("Upload count must match prompt count.")
        if not uploaded_files:
            raise ValueError("At least one task is required.")
        if len(uploaded_files) > self.config.max_tasks_per_batch:
            raise ValueError(f"At most {self.config.max_tasks_per_batch} tasks are allowed.")
        for prompt in prompts:
            stripped = prompt.strip()
            if not stripped:
                raise ValueError("Prompt cannot be empty.")
            if len(stripped) > self.config.max_prompt_chars:
                raise ValueError(
                    f"Prompt must be at most {self.config.max_prompt_chars} characters."
                )
        for uploaded_file in uploaded_files:
            size = self._uploaded_size(uploaded_file)
            if size > self.config.max_image_bytes:
                raise ValueError("Image must be 15 MB or smaller.")

    def _validate_real_submission(
        self,
        uploaded_files: list[BinaryIO],
        image_urls: list[str | None] | None,
        concurrency_limit: int,
        real_api_confirmed: bool,
        maximum_cost_usd: float | None,
        expected_confirmation: str,
    ) -> None:
        if len(uploaded_files) != self.config.real_video_max_tasks:
            raise ValueError("Seedance mode allows exactly one task.")
        if concurrency_limit != self.config.real_video_max_concurrency:
            raise ValueError("Seedance mode requires concurrency 1.")
        if not expected_confirmation.startswith("CONFIRM REAL "):
            raise ValueError("Seedance mode requires CONFIRM REAL <batch_id>.")
        if not real_api_confirmed:
            raise ValueError("Paid API confirmation checkbox is required.")
        self.config.validate_seedance_config()
        if maximum_cost_usd is None:
            raise ValueError(
                "Operator cost acknowledgement amount is required for real provider mode."
            )
        if not image_urls or len(image_urls) != len(uploaded_files):
            raise ValueError("Seedance mode requires a task-specific image_url.")
        for image_url in image_urls:
            self._validate_seedance_image_url(image_url)

    def _validate_seedance_image_url(self, image_url: str | None) -> None:
        if not image_url or not image_url.strip():
            raise ValueError("Seedance mode requires a task-specific image_url.")
        parsed = urlparse(image_url.strip())
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Seedance image_url must be an HTTPS URL.")

    def _validate_batch_id(self, batch_id: str) -> None:
        if not batch_id or not SAFE_ID_RE.fullmatch(batch_id):
            raise ValueError(
                "Batch ID may only contain letters, numbers, underscores, and hyphens."
            )

    def _save_and_validate_upload(
        self,
        batch_id: str,
        task_id: str,
        uploaded_file: BinaryIO,
    ) -> Path:
        name = getattr(uploaded_file, "name", f"{task_id}.png")
        suffix = Path(name).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg"}:
            suffix = ".png"
        target = self.config.uploads_dir / batch_id / f"{task_id}{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        storage_root = self.config.storage_dir.resolve()
        if not self._is_within(target, storage_root):
            raise ValueError("Upload path escapes storage.")
        with target.open("wb") as output:
            shutil.copyfileobj(uploaded_file, output)
        with suppress(AttributeError, OSError):
            uploaded_file.seek(0)
        if target.stat().st_size > self.config.max_image_bytes:
            raise ValueError("Image must be 15 MB or smaller.")
        self._validate_image(target)
        return target

    def _validate_image(self, path: Path) -> None:
        try:
            with Image.open(path) as image:
                image.verify()
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("Uploaded file must be a valid image.") from exc

    def _uploaded_size(self, uploaded_file: BinaryIO) -> int:
        size = getattr(uploaded_file, "size", None)
        if isinstance(size, int):
            return size
        with suppress(AttributeError, OSError):
            current = uploaded_file.tell()
            uploaded_file.seek(0, 2)
            end = uploaded_file.tell()
            uploaded_file.seek(current)
            return end
        return 0

    def _is_within(self, path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root)
        except ValueError:
            return False
        return True


class PathUpload:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.name = path.name
        self.size = path.stat().st_size
        self._handle = path.open("rb")

    def read(self, size: int = -1) -> bytes:
        return self._handle.read(size)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._handle.seek(offset, whence)

    def tell(self) -> int:
        return self._handle.tell()

    def close(self) -> None:
        self._handle.close()


__all__ = ["RetryNotAllowedError", "WorkbenchService"]
