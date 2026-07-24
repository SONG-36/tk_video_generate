from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from tk_video_generate.config import AppConfig
from tk_video_generate.enums import TaskStatus
from tk_video_generate.services.workbench_service import WorkbenchService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one real Seedance smoke test.")
    parser.add_argument("--allow-real-api", action="store_true")
    parser.add_argument("--human-confirm", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--max-cost-usd", type=float, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.allow_real_api or args.human_confirm != "CONFIRM REAL SMOKE":
        print("Refusing to call real API without --allow-real-api and CONFIRM REAL SMOKE.")
        return 2

    image_path = Path(args.image)
    if not image_path.is_absolute() or not image_path.exists():
        print("--image must be an existing absolute path.")
        return 2

    config = AppConfig.from_env()
    try:
        config.validate_seedance_config()
    except ValueError as exc:
        print(str(exc))
        return 2
    if args.max_cost_usd > config.real_video_max_cost_usd:
        print("Requested max cost exceeds configured safety ceiling.")
        return 2

    print("Provider: BytePlus ModelArk Seedance")
    print(f"Model: {config.seedance_model}")
    print("Cost estimate: unknown; real charges may apply.")

    service = WorkbenchService(config)
    service.start_worker()
    batch_id = service.new_batch_id()
    batch = service.create_batch_from_paths(
        batch_id=batch_id,
        batch_name="Real Seedance Smoke",
        image_paths=[image_path],
        prompts=[args.prompt],
        duration_seconds=5,
        aspect_ratio="9:16",
        concurrency_limit=1,
        provider_name="byteplus_seedance",
    )

    deadline = time.monotonic() + (config.seedance_max_poll_minutes * 60)
    last_task = None
    while time.monotonic() < deadline:
        tasks = service.list_tasks(batch.id)
        last_task = tasks[0]
        print(f"status={last_task.status.value} provider_task_id={last_task.provider_task_id}")
        if last_task.status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
            break
        time.sleep(config.seedance_poll_interval_seconds)

    service.stop_worker()
    if last_task is None:
        return 1
    if last_task.status is TaskStatus.SUCCEEDED:
        print(f"output={last_task.output_video_path}")
        return 0
    print(f"failed={last_task.error_code} {last_task.error_message}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
