from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app.models.video import (
    VideoAspectRatio,
    VideoDurationMode,
    VideoModel,
    VideoOutputFormat,
    VideoReferenceMode,
    VideoResolution,
)


@dataclass(frozen=True)
class VideoProviderUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class VideoGenerationRequest:
    task_id: int
    prompt: str
    reference_mode: VideoReferenceMode
    resolution: VideoResolution
    aspect_ratio: VideoAspectRatio
    duration_mode: VideoDurationMode
    fixed_duration: int | None
    output_sound: bool
    output_format: VideoOutputFormat
    model: VideoModel
    reference_paths: list[Path]


@dataclass(frozen=True)
class VideoGenerationResult:
    provider_task_id: str | None
    content: bytes
    extension: str = "mp4"
    usage: VideoProviderUsage | None = None


class VideoGenerationProvider(ABC):
    name: str
    model: str

    @abstractmethod
    async def generate(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        raise NotImplementedError
