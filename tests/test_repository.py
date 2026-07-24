from __future__ import annotations

from tk_video_generate.enums import TaskStatus
from tk_video_generate.repositories.sqlite_repository import SQLiteRepository
from tk_video_generate.services.time import now_iso
from tk_video_generate.services.workbench_service import WorkbenchService


def test_repository_persists_batches_and_tasks(app_config, sample_image) -> None:
    service = WorkbenchService(app_config)
    batch = service.create_batch_from_paths(
        batch_id="BATCH_TEST_REPO",
        batch_name="Repository Test",
        image_paths=[sample_image],
        prompts=["normal prompt"],
        duration_seconds=3,
        aspect_ratio="16:9",
        concurrency_limit=1,
    )

    reopened = SQLiteRepository(app_config.database_path)

    assert reopened.get_batch(batch.id) == batch
    tasks = reopened.list_tasks(batch.id)
    assert len(tasks) == 1
    assert tasks[0].status is TaskStatus.QUEUED


def test_recover_running_tasks(app_config, sample_image) -> None:
    service = WorkbenchService(app_config)
    batch = service.create_batch_from_paths(
        batch_id="BATCH_TEST_RECOVER",
        batch_name="Recover Test",
        image_paths=[sample_image],
        prompts=["normal prompt"],
        duration_seconds=3,
        aspect_ratio="16:9",
        concurrency_limit=1,
    )
    task = service.list_tasks(batch.id)[0]
    service.repository.mark_running(task.id, now_iso())

    recovered = service.repository.recover_running_tasks(now_iso())

    assert recovered == 1
    assert service.get_task(task.id).status is TaskStatus.QUEUED
