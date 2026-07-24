from __future__ import annotations

from tk_video_generate.config import AppConfig
from tk_video_generate.enums import ProviderName
from tk_video_generate.providers.base import VideoProvider
from tk_video_generate.providers.byteplus_seedance import BytePlusSeedanceProvider
from tk_video_generate.providers.mock_provider import MockVideoProvider


def create_provider(name: str, config: AppConfig) -> VideoProvider:
    normalized = name.strip().lower()
    if normalized == ProviderName.MOCK.value:
        return MockVideoProvider(config)
    if normalized in {ProviderName.BYTEPLUS_SEEDANCE.value, "seedance"}:
        return BytePlusSeedanceProvider(config)
    raise ValueError(f"Unknown provider: {name}")
