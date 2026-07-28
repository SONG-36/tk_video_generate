from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_database: str = "tiktok_operations"
    mysql_user: str = "tiktok"
    mysql_password: str = Field(default="", repr=False)
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = Field(default="", repr=False)
    storage_root: Path = Path("../storage")
    image_worker_concurrency: int = Field(default=2, ge=1)
    video_worker_concurrency: int = Field(default=1, ge=1)
    image_provider: str = "mock"
    video_provider: str = "mock"
    openai_api_key: str = Field(default="", repr=False)
    openai_image_model: str = "gpt-image-2"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_request_timeout: float = Field(default=180.0, gt=0)
    openai_organization: str = ""
    openai_project: str = ""
    ark_api_key: str = Field(default="", repr=False)
    ark_video_model: str = "doubao-seedance-2-0-260128"
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    ark_request_timeout: float = Field(default=60.0, gt=0)
    ark_video_poll_interval: float = Field(default=5.0, gt=0)
    ark_video_poll_network_retries: int = Field(default=3, ge=0, le=10)
    ark_video_poll_retry_base_delay: float = Field(default=2.0, gt=0)
    ark_video_generation_timeout: float = Field(default=900.0, gt=0)
    ark_video_max_download_mb: int = Field(default=200, ge=1)

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"
        )

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return (
                f"redis://:{self.redis_password}"
                f"@{self.redis_host}:{self.redis_port}/{self.redis_db}"
            )

        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
