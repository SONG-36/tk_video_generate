from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

from tk_video_generate.config import AppConfig
from tk_video_generate.enums import ProviderName, TaskStatus
from tk_video_generate.models import VideoTask
from tk_video_generate.providers.byteplus_seedance import BytePlusSeedanceProvider
from tk_video_generate.services.workbench_service import WorkbenchService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one Seedance smoke test.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-real-api", action="store_true")
    parser.add_argument("--human-confirm")
    parser.add_argument("--image-url", required=True)
    parser.add_argument("--local-preview-image")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--duration", type=int, default=5)
    parser.add_argument("--aspect-ratio", default="9:16")
    parser.add_argument("--model")
    parser.add_argument("--operator-max-cost-ack-usd", type=float, default=1.0)
    parser.add_argument("--output-json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    image_url = args.image_url.strip()
    parsed_url = urlparse(image_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        print("--image-url must be a public HTTPS URL.")
        return 2

    config = AppConfig.from_env()
    if args.model:
        config = _config_with_model(config, args.model)

    if args.dry_run:
        return run_dry_run(args, config, image_url, parsed_url.netloc)

    return run_real_smoke(args, config, image_url, parsed_url.netloc)


def run_dry_run(
    args: argparse.Namespace,
    config: AppConfig,
    image_url: str,
    image_url_host: str,
) -> int:
    dry_config = _config_for_dry_run(config)
    provider = BytePlusSeedanceProvider(dry_config)
    task = _smoke_task(
        image_path=args.local_preview_image or "[LOCAL_PREVIEW_NOT_SENT]",
        image_url=image_url,
        prompt=args.prompt,
        duration_seconds=args.duration,
        aspect_ratio=args.aspect_ratio,
        model=dry_config.seedance_model,
    )
    request = provider.build_redacted_request(task)
    output_path = Path(args.output_json) if args.output_json else Path(
        tempfile.gettempdir()
    ) / "seedance-smoke-dry-run.json"
    output_path.write_text(json.dumps(request, indent=2, ensure_ascii=True), encoding="utf-8")

    print("provider=BytePlus ModelArk Seedance")
    print(f"base_url={dry_config.seedance_base_url.rstrip('/')}")
    print(f"model={dry_config.seedance_model}")
    print("image_input_type=https_url")
    print(f"image_url_host={image_url_host}")
    print(f"prompt_length={len(args.prompt)}")
    print(f"duration={args.duration}")
    print(f"aspect_ratio={args.aspect_ratio}")
    print("cost_estimate_status=unknown")
    print(f"endpoint={request['url']}")
    print(f"dry_run_request_json={output_path}")
    print(json.dumps(request, indent=2, ensure_ascii=True))
    return 0


def run_real_smoke(
    args: argparse.Namespace,
    config: AppConfig,
    image_url: str,
    image_url_host: str,
) -> int:
    if not args.allow_real_api or args.human_confirm != "CONFIRM REAL SMOKE":
        print("Refusing to call real API without --allow-real-api and CONFIRM REAL SMOKE.")
        return 2
    if not args.local_preview_image:
        print("--local-preview-image is required for local task record; Seedance uses --image-url.")
        return 2
    image_path = Path(args.local_preview_image)
    if not image_path.is_absolute() or not image_path.exists():
        print("--local-preview-image must be an existing absolute path.")
        return 2
    try:
        config.validate_seedance_config()
    except ValueError as exc:
        print(str(exc))
        return 2
    if args.operator_max_cost_ack_usd > config.real_video_max_cost_usd:
        print("Operator acknowledgment exceeds configured local safety value.")
        return 2

    print("provider=BytePlus ModelArk Seedance")
    print(f"base_url={config.seedance_base_url.rstrip('/')}")
    print(f"model={config.seedance_model}")
    print("image_input_type=https_url")
    print(f"image_url_host={image_url_host}")
    print(f"prompt_length={len(args.prompt)}")
    print(f"duration={args.duration}")
    print(f"aspect_ratio={args.aspect_ratio}")
    print("cost_estimate_status=unknown")
    print("Cost estimate is unknown; acknowledgment is not a provider-enforced ceiling.")

    service = WorkbenchService(config)
    service.start_worker()
    batch_id = service.new_batch_id()
    batch = service.create_batch_from_paths(
        batch_id=batch_id,
        batch_name="Real Seedance Smoke",
        image_paths=[image_path],
        prompts=[args.prompt],
        duration_seconds=args.duration,
        aspect_ratio=args.aspect_ratio,
        concurrency_limit=1,
        provider_name=ProviderName.BYTEPLUS_SEEDANCE.value,
        image_urls=[image_url],
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


def _config_for_dry_run(config: AppConfig) -> AppConfig:
    return AppConfig(
        project_root=config.project_root,
        database_path=config.database_path,
        storage_dir=config.storage_dir,
        uploads_dir=config.uploads_dir,
        outputs_dir=config.outputs_dir,
        archives_dir=config.archives_dir,
        ffmpeg_path=config.ffmpeg_path,
        ffprobe_path=config.ffprobe_path,
        seedance_api_key="[DRY_RUN_NOT_USED]",
        seedance_base_url=config.seedance_base_url,
        seedance_model=config.seedance_model or "UNCONFIGURED_SEEDANCE_MODEL",
        seedance_request_timeout_seconds=config.seedance_request_timeout_seconds,
    )


def _config_with_model(config: AppConfig, model: str) -> AppConfig:
    return AppConfig(
        project_root=config.project_root,
        database_path=config.database_path,
        storage_dir=config.storage_dir,
        uploads_dir=config.uploads_dir,
        outputs_dir=config.outputs_dir,
        archives_dir=config.archives_dir,
        ffmpeg_path=config.ffmpeg_path,
        ffprobe_path=config.ffprobe_path,
        seedance_api_key=config.seedance_api_key,
        seedance_base_url=config.seedance_base_url,
        seedance_model=model,
        seedance_poll_interval_seconds=config.seedance_poll_interval_seconds,
        seedance_request_timeout_seconds=config.seedance_request_timeout_seconds,
        seedance_max_poll_minutes=config.seedance_max_poll_minutes,
    )


def _smoke_task(
    image_path: str,
    image_url: str,
    prompt: str,
    duration_seconds: int,
    aspect_ratio: str,
    model: str | None,
) -> VideoTask:
    return VideoTask(
        id="SMOKE_TASK",
        batch_id="SMOKE_BATCH",
        name="Smoke",
        image_path=image_path,
        prompt=prompt,
        provider=ProviderName.BYTEPLUS_SEEDANCE.value,
        model=model,
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
        status=TaskStatus.DRAFT,
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
        image_url=image_url,
    )


if __name__ == "__main__":
    sys.exit(main())
