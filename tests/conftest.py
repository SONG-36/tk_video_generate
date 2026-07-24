from __future__ import annotations

import io
import time
from pathlib import Path

import pytest
from PIL import Image

from tk_video_generate.config import AppConfig
from tk_video_generate.enums import TaskStatus
from tk_video_generate.services.workbench_service import WorkbenchService


class FakeUpload(io.BytesIO):
    def __init__(self, data: bytes, name: str = "first_frame.png", size: int | None = None) -> None:
        super().__init__(data)
        self.name = name
        self.size = len(data) if size is None else size


@pytest.fixture
def app_config(tmp_path: Path) -> AppConfig:
    storage_dir = tmp_path / "storage"
    return AppConfig(
        project_root=tmp_path,
        database_path=tmp_path / "data" / "app.db",
        storage_dir=storage_dir,
        uploads_dir=storage_dir / "uploads",
        outputs_dir=storage_dir / "outputs",
        archives_dir=storage_dir / "archives",
        mock_timeout_seconds=0.05,
    )


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    path = tmp_path / "first_frame.png"
    Image.new("RGB", (160, 90), color=(30, 90, 160)).save(path)
    return path


@pytest.fixture
def image_upload_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (160, 90), color=(30, 90, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


def make_upload(data: bytes, name: str = "first_frame.png", size: int | None = None) -> FakeUpload:
    return FakeUpload(data=data, name=name, size=size)


def create_batch(
    service: WorkbenchService,
    sample_image: Path,
    batch_id: str = "BATCH_TEST",
    prompts: list[str] | None = None,
    aspect_ratio: str = "16:9",
    duration_seconds: int = 3,
    concurrency_limit: int = 3,
):
    prompts = prompts or ["normal prompt"]
    return service.create_batch_from_paths(
        batch_id=batch_id,
        batch_name=batch_id,
        image_paths=[sample_image] * len(prompts),
        prompts=prompts,
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
        concurrency_limit=concurrency_limit,
    )


def wait_for_terminal(
    service: WorkbenchService,
    batch_id: str,
    timeout_seconds: float = 10,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        tasks = service.list_tasks(batch_id)
        statuses = {task.status for task in tasks}
        if tasks and statuses <= {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
            return
        time.sleep(0.05)
    raise AssertionError("Tasks did not reach terminal state.")
