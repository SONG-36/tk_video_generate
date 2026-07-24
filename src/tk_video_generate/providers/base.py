from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tk_video_generate.models import VideoTask


class ProviderError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ProviderSubmission:
    provider_task_id: str
    raw_response: dict[str, Any]


@dataclass(frozen=True)
class ProviderPollResult:
    status: str
    progress: int | None
    result_url: str | None
    error_code: str | None
    error_message: str | None
    raw_response: dict[str, Any]


class VideoProvider(ABC):
    name: str

    @abstractmethod
    def validate(self, task: VideoTask) -> None:
        raise NotImplementedError

    @abstractmethod
    def estimate_cost(self, task: VideoTask) -> float | None:
        raise NotImplementedError

    @abstractmethod
    def submit(self, task: VideoTask, output_dir: Path) -> ProviderSubmission:
        raise NotImplementedError

    @abstractmethod
    def poll(self, provider_task_id: str) -> ProviderPollResult:
        raise NotImplementedError

    @abstractmethod
    def download(self, result_url: str, output_path: Path) -> Path:
        raise NotImplementedError

    def estimate_batch_cost(self, task_count: int, duration_seconds: int) -> float | None:
        return round(task_count * duration_seconds * 0.01, 2)
