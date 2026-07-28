from app.core.config import Settings, get_settings
from app.providers.video.base import VideoGenerationProvider
from app.providers.video.mock import MockVideoGenerationProvider
from app.providers.video.volcengine_ark_provider import (
    VolcengineArkVideoGenerationProvider,
)


def create_video_provider(settings: Settings | None = None) -> VideoGenerationProvider:
    current = settings or get_settings()
    provider_name = current.video_provider.strip().lower()
    if provider_name == "mock":
        return MockVideoGenerationProvider()
    if provider_name == "volcengine_ark":
        return VolcengineArkVideoGenerationProvider(
            api_key=current.ark_api_key,
            model=current.ark_video_model,
            base_url=current.ark_base_url,
            request_timeout=current.ark_request_timeout,
            poll_interval=current.ark_video_poll_interval,
            poll_network_retries=current.ark_video_poll_network_retries,
            poll_retry_base_delay=current.ark_video_poll_retry_base_delay,
            generation_timeout=current.ark_video_generation_timeout,
            max_download_bytes=current.ark_video_max_download_mb * 1024 * 1024,
        )
    raise ValueError(f"不支持的 VIDEO_PROVIDER: {current.video_provider}")
