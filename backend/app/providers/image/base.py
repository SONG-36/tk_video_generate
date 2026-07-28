from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app.models.image import ImageAspectRatio, ImageOutputFormat


@dataclass(frozen=True)
class ImageProviderUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class ImageGenerationRequest:
    task_id: int
    prompt: str
    aspect_ratio: ImageAspectRatio
    image_count: int
    output_format: ImageOutputFormat
    reference_paths: list[Path]


@dataclass(frozen=True)
class GeneratedImage:
    content: bytes
    extension: str = "png"


@dataclass(frozen=True)
class ImageGenerationResult:
    provider_task_id: str | None
    images: list[GeneratedImage]
    usage: ImageProviderUsage | None = None


class ImageGenerationProvider(ABC):
    name: str
    model: str

    @abstractmethod
    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        raise NotImplementedError

