import asyncio
import os

import pytest

from app.core.config import Settings
from app.models.image import ImageAspectRatio, ImageOutputFormat
from app.providers.image.base import ImageGenerationRequest
from app.providers.image.openai_provider import OpenAIImageGenerationProvider


@pytest.mark.live
def test_openai_image_provider_live_smoke() -> None:
    if os.getenv("OPENAI_LIVE_TEST") != "1":
        pytest.skip("Set OPENAI_LIVE_TEST=1 to allow one paid OpenAI image request")

    settings = Settings()
    if not settings.openai_api_key:
        pytest.fail("OPENAI_LIVE_TEST=1 requires OPENAI_API_KEY")

    provider = OpenAIImageGenerationProvider(
        api_key=settings.openai_api_key,
        model=settings.openai_image_model,
        base_url=settings.openai_base_url,
        timeout=settings.openai_request_timeout,
        organization=settings.openai_organization,
        project=settings.openai_project,
    )
    request = ImageGenerationRequest(
        task_id=0,
        prompt=(
            "A minimal product photography test: one matte white cube centered "
            "on a light gray studio background, soft shadow, no text."
        ),
        aspect_ratio=ImageAspectRatio.SQUARE_1_1,
        image_count=1,
        output_format=ImageOutputFormat.PNG,
        reference_paths=[],
    )

    async def run() -> None:
        try:
            result = await provider.generate(request)
        finally:
            await provider.close()
        assert result.provider_task_id
        assert len(result.images) == 1
        assert result.images[0].content.startswith(b"\x89PNG\r\n\x1a\n")

    asyncio.run(run())
