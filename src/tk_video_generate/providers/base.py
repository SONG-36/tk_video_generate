from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from tk_video_generate.models import VideoTask


class ProviderError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class VideoProvider(ABC):
    name: str

    @abstractmethod
    def estimate_cost(self, task_count: int, duration_seconds: int) -> float:
        raise NotImplementedError

    @abstractmethod
    def generate(self, task: VideoTask, output_dir: Path) -> dict[str, object]:
        raise NotImplementedError
