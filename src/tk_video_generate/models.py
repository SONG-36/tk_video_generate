from __future__ import annotations

from dataclasses import dataclass

from tk_video_generate.enums import BatchStatus, TaskStatus


@dataclass(frozen=True)
class VideoBatch:
    id: str
    name: str
    provider: str
    status: BatchStatus
    concurrency_limit: int
    confirmation_text: str
    total_tasks: int
    created_at: str


@dataclass(frozen=True)
class VideoTask:
    id: str
    batch_id: str
    name: str
    image_path: str
    prompt: str
    provider: str
    duration_seconds: int
    aspect_ratio: str
    status: TaskStatus
    progress: int
    provider_task_id: str | None
    output_video_path: str | None
    request_json_path: str | None
    result_json_path: str | None
    retry_count: int
    error_code: str | None
    error_message: str | None
    created_at: str
    updated_at: str
    completed_at: str | None
    model: str | None = None
    image_url: str | None = None
    provider_status: str | None = None
    result_url: str | None = None
    estimated_cost: float | None = None
    actual_cost: float | None = None
    provider_response_path: str | None = None
    provider_request_path: str | None = None
    provider_error_payload_path: str | None = None
    submitted_at: str | None = None
    last_polled_at: str | None = None
    next_poll_at: str | None = None
    poll_count: int = 0
    download_started_at: str | None = None
