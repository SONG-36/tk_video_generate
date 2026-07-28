from app.models.video import (
    VideoAspectRatio,
    VideoDurationMode,
    VideoOutputFormat,
    VideoReferenceMode,
    VideoResolution,
)
from app.providers.video.base import (
    VideoGenerationProvider,
    VideoGenerationRequest,
    VideoGenerationResult,
)


class VideoGenerationService:
    def __init__(self, provider: VideoGenerationProvider):
        self.provider = provider

    async def run_mock(self, task_id: int) -> VideoGenerationResult:
        return await self.provider.generate(
            VideoGenerationRequest(
                task_id=task_id,
                prompt="mock video prompt",
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
