from __future__ import annotations

import json
import subprocess
import sys
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from tk_video_generate.config import AppConfig
from tk_video_generate.enums import BatchStatus, TaskStatus
from tk_video_generate.services.workbench_service import WorkbenchService


def wait_for_statuses(
    service: WorkbenchService,
    batch_id: str,
    terminal: bool = True,
    timeout_seconds: float = 20,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        tasks = service.list_tasks(batch_id)
        statuses = {task.status for task in tasks}
        if terminal and len(tasks) == 3 and statuses <= {TaskStatus.SUCCEEDED, TaskStatus.FAILED}:
            return
        if not terminal and tasks:
            return
        time.sleep(0.1)
    raise RuntimeError("Timed out waiting for expected task statuses.")


def ffprobe_video(config: AppConfig, video_path: str) -> dict[str, object]:
    completed = subprocess.run(
        [
            config.ffprobe_path,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,pix_fmt,width,height",
            "-of",
            "json",
            video_path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr)
    return json.loads(completed.stdout)["streams"][0]


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
            "normal prompt for 9:16 playable mp4",
            "[mock-fail] forced failure",
            "[mock-timeout] simulated timeout",
        ],
        duration_seconds=3,
        aspect_ratio="9:16",
        concurrency_limit=3,
    )
    wait_for_statuses(service, batch.id)
    first_pass_tasks = service.list_tasks(batch.id)
    success, forced_failure, timeout_failure = first_pass_tasks
    first_batch_status = service.get_batch_status(batch.id)

    if success.output_video_path is None:
        raise RuntimeError("Successful task did not store an MP4 path.")
    stream = ffprobe_video(config, success.output_video_path)

    retry_before = forced_failure.retry_count
    retried = service.retry_task(forced_failure.id)
    retry_after = retried.retry_count
    wait_for_statuses(service, batch.id)
    after_retry_task = service.get_task(forced_failure.id)
    if after_retry_task is None:
        raise RuntimeError("Retried task disappeared.")
    service.stop_worker()

    refreshed_service = WorkbenchService(config)
    refreshed_tasks = refreshed_service.list_tasks(batch.id)
    refreshed_batch = refreshed_service.get_batch(batch.id)
    zip_path = refreshed_service.create_batch_zip(batch.id)
    if zip_path is None:
        raise RuntimeError("ZIP creation returned None.")
    with zipfile.ZipFile(zip_path) as archive:
        zip_names = archive.namelist()

    summary = {
        "batch_id": batch.id,
        "task_statuses_after_first_pass": [task.status.value for task in first_pass_tasks],
        "batch_status_after_first_pass": first_batch_status.value,
        "ffprobe": stream,
        "retry_before": retry_before,
        "retry_after_requeue": retry_after,
        "retried_status_after_requeue": retried.status.value,
        "retried_final_status": after_retry_task.status.value,
        "retried_final_error_code": after_retry_task.error_code,
        "retried_final_retry_count": after_retry_task.retry_count,
        "content_editing_supported": False,
        "content_editing_note": (
            "Task prompt editing is not supported in V0.1, "
            "so retried mock-fail tasks fail again."
        ),
        "refreshed_task_count": len(refreshed_tasks),
        "refreshed_batch_status": refreshed_batch.status.value if refreshed_batch else None,
        "zip_path": str(zip_path),
        "zip_entries": zip_names,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=True))

    checks = [
        success.status is TaskStatus.SUCCEEDED,
        forced_failure.status is TaskStatus.FAILED,
        forced_failure.error_code == "MOCK_FORCED_FAILURE",
        timeout_failure.status is TaskStatus.FAILED,
        timeout_failure.error_code == "MOCK_TIMEOUT",
        first_batch_status is BatchStatus.PARTIAL_SUCCESS,
        stream["width"] == 540,
        stream["height"] == 960,
        stream["codec_name"] == "h264",
        stream["pix_fmt"] == "yuv420p",
        retry_before == 0,
        retried.status is TaskStatus.QUEUED,
        retry_after == 1,
        after_retry_task.status is TaskStatus.FAILED,
        after_retry_task.error_code == "MOCK_FORCED_FAILURE",
        after_retry_task.retry_count == 1,
        len(refreshed_tasks) == 3,
        refreshed_batch is not None,
        refreshed_batch.status is BatchStatus.PARTIAL_SUCCESS,
        bool(zip_names),
        all(name.startswith(f"{batch.id}/") for name in zip_names),
        all(not Path(name).is_absolute() and ".." not in Path(name).parts for name in zip_names),
    ]
    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
