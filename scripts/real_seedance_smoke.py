from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

from tk_video_generate.config import AppConfig
from tk_video_generate.enums import TaskStatus
from tk_video_generate.models import VideoTask
from tk_video_generate.providers.byteplus_seedance import BytePlusSeedanceProvider
from tk_video_generate.services.workbench_service import WorkbenchService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run or dry-run one Seedance smoke test.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-real-api", action="store_true")
    parser.add_argument("--human-confirm", default="")
    parser.add_argument("--image-url", required=True)
    parser.add_argument("--local-preview-image")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--duration", type=int, default=5)
    parser.add_argument("--aspect-ratio", default="9:16")
    parser.add_argument("--model")
    parser.add_argument("--operator-cost-ack-usd", type=float, default=1.0)
    parser.add_argument("--dry-run-output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    image_url = validate_https_image_url(args.image_url)
    config = AppConfig.from_env()
    model = args.model or config.seedance_model or "UNCONFIRMED_MODEL_OR_ENDPOINT_ID"

    if args.dry_run:
        return run_dry_run(args, config, model, image_url)

    if not args.allow_real_api or args.human_confirm != "CONFIRM REAL SMOKE":
        print("Refusing to call real API without --allow-real-api and CONFIRM REAL SMOKE.")
        return 2
    if not args.local_preview_image:
        print(
            "--local-preview-image is required for real execution and is only "
            "a local preview/audit file."
        )
        return 2
    preview_path = Path(args.local_preview_image)
    if not preview_path.is_absolute() or not preview_path.exists():
        print("--local-preview-image must be an existing absolute path.")
        return 2

    try:
        config.validate_seedance_config()
    except ValueError as exc:
        print(str(exc))
        return 2

    print_redacted_summary(
        config=config,
        model=config.seedance_model or model,
        image_url=image_url,
        prompt=args.prompt,
        duration=args.duration,
        aspect_ratio=args.aspect_ratio,
    )
    print(
        "cost_acknowledgement: operator acknowledged unknown cost; "
        "not a Provider-enforced ceiling"
    )

    service = WorkbenchService(config)
    service.start_worker()
    batch_id = service.new_batch_id()
    batch = service.create_batch_from_paths(
        batch_id=batch_id,
        batch_name="Real Seedance Smoke",
        image_paths=[preview_path],
        image_urls=[image_url],
        prompts=[args.prompt],
        duration_seconds=args.duration,
        aspect_ratio=args.aspect_ratio,
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


def run_dry_run(
    args: argparse.Namespace,
    config: AppConfig,
    model: str,
    image_url: str,
) -> int:
    dry_config = AppConfig(
        project_root=config.project_root,
        database_path=config.database_path,
        storage_dir=config.storage_dir,
        uploads_dir=config.uploads_dir,
        outputs_dir=config.outputs_dir,
        archives_dir=config.archives_dir,
        ffmpeg_path=config.ffmpeg_path,
        ffprobe_path=config.ffprobe_path,
        seedance_api_key="DRY_RUN_API_KEY",
        seedance_base_url=config.seedance_base_url,
        seedance_model=model,
        seedance_request_timeout_seconds=config.seedance_request_timeout_seconds,
    )
    provider = BytePlusSeedanceProvider(dry_config)
    task = VideoTask(
        id="DRY_RUN_TASK",
        batch_id="DRY_RUN_BATCH",
        name="Dry Run Task",
        image_path="[local-preview-not-submitted]",
        image_url=image_url,
        prompt=args.prompt,
        provider="byteplus_seedance",
        duration_seconds=args.duration,
        aspect_ratio=args.aspect_ratio,
        status=TaskStatus.QUEUED,
        progress=0,
        provider_task_id=None,
        output_video_path=None,
        request_json_path=None,
        result_json_path=None,
        retry_count=0,
        error_code=None,
        error_message=None,
        created_at="dry-run",
        updated_at="dry-run",
        completed_at=None,
        model=model,
        estimated_cost=None,
    )
    payload = provider.request_payload(task)
    redacted_payload = provider.redacted_payload(payload)
    output_path = Path(args.dry_run_output) if args.dry_run_output else Path(
        tempfile.gettempdir()
    ) / "seedance_dry_run_request.json"
    output = {
        "method": "POST",
        "endpoint": f"{dry_config.seedance_base_url.rstrip('/')}/contents/generations/tasks",
        "headers": {
            "Content-Type": "application/json",
            "Authorization": "Bearer [REDACTED]",
        },
        "image_input_type": "https_url",
        "image_url_host": urlparse(image_url).netloc,
        "model_field": "model",
        "cost_estimate_status": "unknown_not_provider_enforced",
        "payload": redacted_payload,
    }
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print_redacted_summary(
        config=dry_config,
        model=model,
        image_url=image_url,
        prompt=args.prompt,
        duration=args.duration,
        aspect_ratio=args.aspect_ratio,
    )
    print(f"endpoint={output['endpoint']}")
    print("image_input_type=https_url")
    print("model_field=model")
    print("cost_estimate_status=unknown_not_provider_enforced")
    print(f"dry_run_output={output_path}")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def validate_https_image_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise SystemExit("--image-url must be an HTTPS URL.")
    return value


def print_redacted_summary(
    *,
    config: AppConfig,
    model: str,
    image_url: str,
    prompt: str,
    duration: int,
    aspect_ratio: str,
) -> None:
    print("provider=BytePlus ModelArk Seedance")
    print(f"base_url={config.seedance_base_url.rstrip('/')}")
    print(f"model={model}")
    print("image_input_type=https_url")
    print(f"image_url_host={urlparse(image_url).netloc}")
    print(f"prompt_length={len(prompt)}")
    print(f"duration={duration}")
    print(f"aspect_ratio={aspect_ratio}")
    print("cost_estimate_status=unknown_not_provider_enforced")


if __name__ == "__main__":
    sys.exit(main())
