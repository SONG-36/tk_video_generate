from app.core.config import Settings, get_settings
from app.providers.image.base import ImageGenerationProvider
from app.providers.image.mock import MockImageGenerationProvider
from app.providers.image.openai_provider import OpenAIImageGenerationProvider


def create_image_provider(settings: Settings | None = None) -> ImageGenerationProvider:
    current = settings or get_settings()
    provider_name = current.image_provider.strip().lower()
    if provider_name == "mock":
        return MockImageGenerationProvider()
    if provider_name == "openai":
        return OpenAIImageGenerationProvider(
            api_key=current.openai_api_key,
            model=current.openai_image_model,
            base_url=current.openai_base_url,
            timeout=current.openai_request_timeout,
            organization=current.openai_organization,
            project=current.openai_project,
        )
    raise ValueError(f"不支持的 IMAGE_PROVIDER: {current.image_provider}")
