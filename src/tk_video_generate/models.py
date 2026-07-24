from __future__ import annotations

from dataclasses import dataclass

from tk_video_generate.enums import TaskStatus


@dataclass(frozen=True)
class VideoBatch:
    id: str
    name: str
    provider: str
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
