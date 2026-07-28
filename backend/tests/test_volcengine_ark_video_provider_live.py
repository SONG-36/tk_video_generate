import asyncio
import os

import pytest

from app.core.config import Settings
from app.models.video import (
    VideoAspectRatio,
    VideoDurationMode,
    VideoOutputFormat,
    VideoReferenceMode,
    VideoResolution,
)
from app.providers.video.base import VideoGenerationRequest, VideoGenerationResult
from app.providers.video.volcengine_ark_provider import (
    VolcengineArkVideoGenerationProvider,
)


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("ARK_VIDEO_LIVE_TEST") != "1",
    reason="需要显式设置 ARK_VIDEO_LIVE_TEST=1，测试会产生真实费用",
)
def test_volcengine_ark_video_provider_live() -> None:
    settings = Settings()
    request = VideoGenerationRequest(
        task_id=0,
        prompt="A paper airplane gliding over a clean white desk, static camera",
        reference_mode=VideoReferenceMode.REFERENCE,
        resolution=VideoResolution.P480,
        aspect_ratio=VideoAspectRatio.LANDSCAPE_16_9,
        duration_mode=VideoDurationMode.FIXED,
        fixed_duration=5,
        output_sound=False,
        output_format=VideoOutputFormat.MP4,
        reference_paths=[],
    )

    async def generate_and_close() -> VideoGenerationResult:
        provider = VolcengineArkVideoGenerationProvider(
            api_key=settings.ark_api_key,
            model=settings.ark_video_model,
            base_url=settings.ark_base_url,
            request_timeout=settings.ark_request_timeout,
            poll_interval=settings.ark_video_poll_interval,
            poll_network_retries=settings.ark_video_poll_network_retries,
            poll_retry_base_delay=settings.ark_video_poll_retry_base_delay,
            generation_timeout=settings.ark_video_generation_timeout,
            max_download_bytes=settings.ark_video_max_download_mb * 1024 * 1024,
        )
        try:
            return await provider.generate(request)
        finally:
            await provider.close()

    result = asyncio.run(generate_and_close())

    assert result.provider_task_id
    assert result.content[4:8] == b"ftyp"
