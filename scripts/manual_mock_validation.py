from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from tk_video_generate.config import AppConfig
from tk_video_generate.enums import TaskStatus
from tk_video_generate.services.workbench_service import WorkbenchService


def wait_for_terminal(
    service: WorkbenchService,
    batch_id: str,
    timeout_seconds: float = 20,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        tasks = service.list_tasks(batch_id)
        statuses = {task.status for task in tasks}
        if statuses <= {TaskStatus.COMPLETED, TaskStatus.FAILED} and len(tasks) == 3:
            return
        time.sleep(0.25)
    raise RuntimeError("Manual validation tasks did not reach terminal state.")


def main() -> int:
    config = AppConfig.from_env()
    config.ensure_directories()
    validation_dir = config.uploads_dir / "_manual_validation_assets"
    validation_dir.mkdir(parents=True, exist_ok=True)
    image_path = validation_dir / "first_frame.png"
    Image.new("RGB", (320, 180), color=(28, 96, 156)).save(image_path)

    batch_id = "BATCH_MANUAL_MOCK_" + datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    service = WorkbenchService(config)
    service.start_worker()
    batch = service.create_batch_from_paths(
        batch_id=batch_id,
        batch_name="Manual Mock Validation",
        image_paths=[image_path, image_path, image_path],
        prompts=[
            "normal prompt for playable mp4",
            "[mock-fail] forced failure",
            "[mock-timeout] simulated timeout",
        ],
        duration_seconds=3,
        aspect_ratio="16:9",
        concurrency_limit=3,
    )
    wait_for_terminal(service, batch.id)
    tasks = service.list_tasks(batch.id)

    success, forced_failure, timeout_failure = tasks
    zip_path = service.create_batch_zip(batch.id)
    service.stop_worker()
    service.retry_task(forced_failure.id)
    retried = service.get_task(forced_failure.id)

    refreshed_service = WorkbenchService(config)
    refreshed_tasks = refreshed_service.list_tasks(batch.id)

    summary = {
        "batch_id": batch.id,
        "success_status": success.status.value,
        "success_video_exists": bool(
            success.output_video_path and Path(success.output_video_path).exists()
        ),
        "success_video_path": success.output_video_path,
        "forced_failure_status": forced_failure.status.value,
        "forced_failure_error_code": forced_failure.error_code,
        "timeout_status": timeout_failure.status.value,
        "timeout_error_code": timeout_failure.error_code,
        "retry_status_after_manual_retry": retried.status.value if retried else None,
        "retry_count_after_manual_retry": retried.retry_count if retried else None,
        "refreshed_task_count": len(refreshed_tasks),
        "zip_exists": bool(zip_path and zip_path.exists()),
        "zip_path": str(zip_path) if zip_path else None,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=True))

    checks = [
        summary["success_status"] == "COMPLETED",
        summary["success_video_exists"] is True,
        summary["forced_failure_status"] == "FAILED",
        summary["forced_failure_error_code"] == "MOCK_FORCED_FAILURE",
        summary["timeout_status"] == "FAILED",
        summary["timeout_error_code"] == "MOCK_TIMEOUT",
        summary["retry_status_after_manual_retry"] == "QUEUED",
        summary["retry_count_after_manual_retry"] == 1,
        summary["refreshed_task_count"] == 3,
        summary["zip_exists"] is True,
    ]
    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
