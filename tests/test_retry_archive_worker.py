from __future__ import annotations

import threading
import time
import zipfile
from pathlib import Path

import pytest
from conftest import create_batch, wait_for_terminal

from tk_video_generate.enums import TaskStatus
from tk_video_generate.providers.mock_provider import MockVideoProvider
from tk_video_generate.repositories.sqlite_repository import RetryNotAllowedError
from tk_video_generate.services.time import now_iso
from tk_video_generate.services.workbench_service import WorkbenchService
from tk_video_generate.services.worker import TaskWorker


def test_failed_task_retry_clears_errors_and_can_execute_again(app_config, sample_image) -> None:
    service = WorkbenchService(app_config)
    create_batch(
        service,
        sample_image,
        batch_id="BATCH_RETRY_EXECUTE",
        prompts=["[mock-fail] fail"],
        concurrency_limit=1,
    )
    service.start_worker()
    wait_for_terminal(service, "BATCH_RETRY_EXECUTE")
    failed = service.list_tasks("BATCH_RETRY_EXECUTE")[0]

    retried = service.retry_task(failed.id)
    assert retried.status is TaskStatus.QUEUED
    assert retried.retry_count == 1
    assert retried.error_code is None
    assert retried.error_message is None

    wait_for_terminal(service, "BATCH_RETRY_EXECUTE")
    failed_again = service.list_tasks("BATCH_RETRY_EXECUTE")[0]
    service.stop_worker()

    assert failed_again.status is TaskStatus.FAILED
    assert failed_again.error_code == "MOCK_FORCED_FAILURE"
    assert failed_again.retry_count == 1


def test_retry_limit_and_non_failed_statuses_are_rejected(app_config, sample_image) -> None:
    service = WorkbenchService(app_config)
    batch = create_batch(
        service,
        sample_image,
        batch_id="BATCH_RETRY_REJECT",
        prompts=["queued", "running", "success", "failed"],
    )
    queued, running, success, failed = service.list_tasks(batch.id)
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

    for task in [queued, running, success]:
        with pytest.raises(RetryNotAllowedError, match="Only FAILED"):
            service.retry_task(task.id)

    assert service.retry_task(failed.id).retry_count == 1
    service.repository.mark_failed(
        failed.id,
        "FAIL",
        "failed",
        Path(failed.image_path),
        Path(failed.image_path),
        now_iso(),
    )
    assert service.retry_task(failed.id).retry_count == 2
    service.repository.mark_failed(
        failed.id,
        "FAIL",
        "failed",
        Path(failed.image_path),
        Path(failed.image_path),
        now_iso(),
    )
    with pytest.raises(RetryNotAllowedError, match="retry limit"):
        service.retry_task(failed.id)


def test_batch_zip_contains_only_target_batch_and_safe_relative_paths(
    app_config,
    sample_image,
) -> None:
    service = WorkbenchService(app_config)
    first_batch = create_batch(service, sample_image, batch_id="BATCH_ZIP_ONE")
    second_batch = create_batch(service, sample_image, batch_id="BATCH_ZIP_TWO")

    first_zip = service.create_batch_zip(first_batch.id)
    second_zip = service.create_batch_zip(first_batch.id)

    assert first_zip == second_zip
    assert first_zip.exists()
    with zipfile.ZipFile(first_zip) as archive:
        names = archive.namelist()

    assert names
    assert all(name.startswith(f"{first_batch.id}/") for name in names)
    assert all(second_batch.id not in name for name in names)
    assert all(not Path(name).is_absolute() and ".." not in Path(name).parts for name in names)


def test_worker_start_is_idempotent(app_config, sample_image) -> None:
    service = WorkbenchService(app_config)
    create_batch(service, sample_image, batch_id="BATCH_WORKER_START")

    service.start_worker()
    first_thread = service.worker.scan_thread
    service.start_worker()
    second_thread = service.worker.scan_thread
    service.stop_worker()

    assert first_thread is second_thread


class RecordingProvider(MockVideoProvider):
    def __init__(self, app_config, delay: float = 0.05, fail_prompt: str | None = None) -> None:
        super().__init__(app_config)
        self.delay = delay
        self.fail_prompt = fail_prompt
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def generate(self, task, output_dir):
        with self.lock:
            self.calls.append(task.id)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self.delay)
            if self.fail_prompt and self.fail_prompt in task.prompt:
                raise RuntimeError("unexpected provider error")
            return super().generate(task, output_dir)
        finally:
            with self.lock:
                self.active -= 1

    def submit(self, task, output_dir):
        if self.fail_prompt and self.fail_prompt in task.prompt:
            raise RuntimeError("unexpected provider error")
        return super().submit(task, output_dir)


def test_two_workers_do_not_execute_same_task_twice(app_config, sample_image) -> None:
    service = WorkbenchService(app_config)
    create_batch(service, sample_image, batch_id="BATCH_TWO_WORKERS", concurrency_limit=1)
    provider = RecordingProvider(app_config)
    worker_one = TaskWorker(app_config, service.repository, provider)
    worker_two = TaskWorker(app_config, service.repository, provider)

    worker_one.start()
    worker_two.start()
    wait_for_terminal(service, "BATCH_TWO_WORKERS")
    worker_one.stop()
    worker_two.stop()

    assert provider.calls.count("BATCH_TWO_WORKERS_TASK_001") == 1


def test_batch_concurrency_limit_one_never_runs_two_tasks_in_parallel(
    app_config,
    sample_image,
) -> None:
    service = WorkbenchService(app_config)
    create_batch(
        service,
        sample_image,
        batch_id="BATCH_CONCURRENCY_ONE",
        prompts=["one", "two"],
        concurrency_limit=1,
    )
    provider = RecordingProvider(app_config, delay=0.2)
    worker = TaskWorker(app_config, service.repository, provider)

    worker.start()
    wait_for_terminal(service, "BATCH_CONCURRENCY_ONE")
    worker.stop()

    assert provider.max_active == 1


def test_task_exception_does_not_stop_other_tasks_or_scan_loop(app_config, sample_image) -> None:
    service = WorkbenchService(app_config)
    create_batch(
        service,
        sample_image,
        batch_id="BATCH_EXCEPTION_CONTINUE",
        prompts=["boom", "normal"],
        concurrency_limit=2,
    )
    provider = RecordingProvider(app_config, fail_prompt="boom")
    worker = TaskWorker(app_config, service.repository, provider)

    worker.start()
    wait_for_terminal(service, "BATCH_EXCEPTION_CONTINUE")
    assert worker.scan_thread is not None and worker.scan_thread.is_alive()
    worker.stop()

    tasks = service.list_tasks("BATCH_EXCEPTION_CONTINUE")
    assert [task.status for task in tasks] == [TaskStatus.FAILED, TaskStatus.SUCCEEDED]
    assert tasks[0].error_code == "UNEXPECTED_ERROR"
