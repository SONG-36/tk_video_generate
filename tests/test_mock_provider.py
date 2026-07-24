from __future__ import annotations

import json
import time
from pathlib import Path

from tk_video_generate.enums import TaskStatus
from tk_video_generate.services.workbench_service import WorkbenchService


def wait_for_terminal(
    service: WorkbenchService,
    batch_id: str,
    timeout_seconds: float = 10,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        statuses = {task.status for task in service.list_tasks(batch_id)}
        if statuses <= {TaskStatus.COMPLETED, TaskStatus.FAILED}:
            return
        time.sleep(0.2)
    raise AssertionError("Tasks did not reach terminal state.")


def test_mock_provider_success_failure_timeout_and_retry(app_config, sample_image: Path) -> None:
    service = WorkbenchService(app_config)
    service.start_worker()
    batch = service.create_batch_from_paths(
        batch_id="BATCH_PROVIDER",
        batch_name="Provider Test",
        image_paths=[sample_image, sample_image, sample_image],
        prompts=["normal prompt", "[mock-fail] fail", "[mock-timeout] timeout"],
        duration_seconds=3,
        aspect_ratio="16:9",
        concurrency_limit=3,
    )

    wait_for_terminal(service, batch.id)
    tasks = service.list_tasks(batch.id)

    assert tasks[0].status is TaskStatus.COMPLETED
    assert tasks[0].output_video_path is not None
    assert Path(tasks[0].output_video_path).exists()

    assert tasks[1].status is TaskStatus.FAILED
    assert tasks[1].error_code == "MOCK_FORCED_FAILURE"

    assert tasks[2].status is TaskStatus.FAILED
    assert tasks[2].error_code == "MOCK_TIMEOUT"

    result = json.loads(Path(tasks[0].result_json_path).read_text(encoding="utf-8"))
    stream = result["ffprobe"]["streams"][0]
    assert stream["codec_name"] == "h264"
    assert stream["pix_fmt"] == "yuv420p"

    service.stop_worker()
    service.retry_task(tasks[1].id)
    retried = service.get_task(tasks[1].id)
    assert retried.status is TaskStatus.QUEUED
    assert retried.retry_count == 1
