import asyncio

from app.models.image import ImageAspectRatio, ImageOutputFormat
from app.models.video import (
    VideoAspectRatio,
    VideoDurationMode,
    VideoOutputFormat,
    VideoReferenceMode,
    VideoResolution,
)
from app.providers.image.base import ImageGenerationProvider, ImageGenerationRequest
from app.providers.image.mock import MockImageGenerationProvider
from app.providers.video.base import VideoGenerationProvider, VideoGenerationRequest
from app.providers.video.factory import create_video_provider
from app.providers.video.mock import MockVideoGenerationProvider
from app.providers.video.volcengine_ark_provider import (
    VolcengineArkVideoGenerationProvider,
)
from app.core.config import Settings


def test_mock_providers_implement_interfaces() -> None:
    image = MockImageGenerationProvider()
    video = MockVideoGenerationProvider()
    request = ImageGenerationRequest(
        task_id=7,
        prompt="test",
        aspect_ratio=ImageAspectRatio.PORTRAIT_9_16,
        image_count=4,
        output_format=ImageOutputFormat.PNG,
        reference_paths=[],
    )
    assert isinstance(image, ImageGenerationProvider)
    assert isinstance(video, VideoGenerationProvider)
    image_result = asyncio.run(image.generate(request))
    assert image_result.provider_task_id == "mock-image-7"
    assert len(image_result.images) == 4
    video_result = asyncio.run(
        video.generate(
            VideoGenerationRequest(
                task_id=8,
                prompt="test",
                reference_mode=VideoReferenceMode.REFERENCE,
                resolution=VideoResolution.P720,
                aspect_ratio=VideoAspectRatio.PORTRAIT_9_16,
                duration_mode=VideoDurationMode.FIXED,
                fixed_duration=5,
                output_sound=False,
                output_format=VideoOutputFormat.MP4,
                reference_paths=[],
            )
        )
    )
    assert video_result.provider_task_id == "mock-video-8"
    assert video_result.content[4:8] == b"ftyp"


def test_video_provider_factory_builds_volcengine_ark() -> None:
    settings = Settings(
        _env_file=None,
        video_provider="volcengine_ark",
        ark_api_key="test-key",
        ark_video_model="test-video-model",
        ark_video_poll_network_retries=4,
        ark_video_poll_retry_base_delay=1.5,
    )
    provider = create_video_provider(settings)
    try:
        assert isinstance(provider, VolcengineArkVideoGenerationProvider)
        assert provider.model == "test-video-model"
        assert provider.poll_network_retries == 4
        assert provider.poll_retry_base_delay == 1.5
    finally:
        asyncio.run(provider.close())
