from __future__ import annotations

import concurrent.futures
from pathlib import Path

from conftest import create_batch

from tk_video_generate.enums import BatchStatus, TaskStatus
from tk_video_generate.repositories.sqlite_repository import SQLiteRepository
from tk_video_generate.services.time import now_iso
from tk_video_generate.services.workbench_service import WorkbenchService


def test_batch_and_task_crud_persist_to_sqlite(app_config, sample_image) -> None:
    service = WorkbenchService(app_config)
    batch = create_batch(service, sample_image, batch_id="BATCH_CRUD")

    reopened = SQLiteRepository(app_config.database_path)
    persisted_batch = reopened.get_batch(batch.id)
    tasks = reopened.list_tasks(batch.id)

    assert persisted_batch is not None
    assert persisted_batch.id == "BATCH_CRUD"
    assert len(tasks) == 1
    assert tasks[0].batch_id == batch.id
    assert tasks[0].status is TaskStatus.QUEUED


def test_recovery_resets_only_running_tasks(app_config, sample_image) -> None:
    service = WorkbenchService(app_config)
    batch = create_batch(
        service,
        sample_image,
        batch_id="BATCH_RECOVER",
        prompts=["running", "success", "fail"],
    )
    running, success, failed = service.list_tasks(batch.id)
    service.repository.mark_running(running.id, now_iso())
    service.repository.mark_succeeded(
        success.id,
        "provider-success",
        Path(success.image_path),
        Path(success.image_path),
        Path(success.image_path),
        now_iso(),
    )
    service.repository.mark_failed(
        failed.id,
        "FAIL",
        "failed",
        Path(failed.image_path),
        Path(failed.image_path),
        now_iso(),
    )

    recovered = service.repository.recover_running_tasks(now_iso())
    tasks = service.list_tasks(batch.id)

    assert recovered == 1
    assert [task.status for task in tasks] == [
        TaskStatus.QUEUED,
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
    ]


def test_same_task_can_only_be_atomically_claimed_once(app_config, sample_image) -> None:
    service = WorkbenchService(app_config)
    batch = create_batch(service, sample_image, batch_id="BATCH_CLAIM")

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = list(
            executor.map(
                lambda _: service.repository.claim_next_queued_task(batch.id, now_iso()),
                range(5),
            )
        )

    claimed = [task for task in results if task is not None]
    assert len(claimed) == 1
    assert service.get_task(claimed[0].id).status is TaskStatus.RUNNING


def test_batch_status_aggregation(app_config, sample_image) -> None:
    service = WorkbenchService(app_config)
    batch = create_batch(
        service,
        sample_image,
        batch_id="BATCH_AGGREGATE",
        prompts=["one", "two"],
    )
    first, second = service.list_tasks(batch.id)

    assert service.get_batch_status(batch.id) is BatchStatus.RUNNING

    service.repository.mark_succeeded(
        first.id,
        "provider-first",
        Path(first.image_path),
        Path(first.image_path),
        Path(first.image_path),
        now_iso(),
    )
    service.repository.mark_succeeded(
        second.id,
        "provider-second",
        Path(second.image_path),
        Path(second.image_path),
        Path(second.image_path),
        now_iso(),
    )
    assert service.get_batch_status(batch.id) is BatchStatus.COMPLETED

    mixed = create_batch(
        service,
        sample_image,
        batch_id="BATCH_PARTIAL",
        prompts=["one", "two"],
    )
    mixed_first, mixed_second = service.list_tasks(mixed.id)
    service.repository.mark_succeeded(
        mixed_first.id,
        "provider-first",
        Path(mixed_first.image_path),
        Path(mixed_first.image_path),
        Path(mixed_first.image_path),
        now_iso(),
    )
    service.repository.mark_failed(
        mixed_second.id,
        "FAIL",
        "failed",
        Path(mixed_second.image_path),
        Path(mixed_second.image_path),
        now_iso(),
    )
    assert service.get_batch_status(mixed.id) is BatchStatus.PARTIAL_SUCCESS

    failed_batch = create_batch(
        service,
        sample_image,
        batch_id="BATCH_ALL_FAILED",
        prompts=["one", "two"],
    )
    for task in service.list_tasks(failed_batch.id):
        service.repository.mark_failed(
            task.id,
            "FAIL",
            "failed",
            Path(task.image_path),
            Path(task.image_path),
            now_iso(),
        )
    assert service.get_batch_status(failed_batch.id) is BatchStatus.FAILED
