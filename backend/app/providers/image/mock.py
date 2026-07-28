from base64 import b64decode

from app.providers.image.base import (
    GeneratedImage,
    ImageGenerationProvider,
    ImageGenerationRequest,
    ImageGenerationResult,
)

MOCK_PNG = b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class MockImageGenerationProvider(ImageGenerationProvider):
    name = "mock"
    model = "mock-image-v1"

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        return ImageGenerationResult(
            provider_task_id=f"mock-image-{request.task_id}",
            images=[GeneratedImage(MOCK_PNG) for _ in range(request.image_count)],
        )

