from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    database_path: Path
    storage_dir: Path
    uploads_dir: Path
    outputs_dir: Path
    archives_dir: Path
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    max_tasks_per_batch: int = 10
    max_worker_threads: int = 5
    max_prompt_chars: int = 5000
    max_image_bytes: int = 15 * 1024 * 1024
    max_retry_count: int = 2
    mock_timeout_seconds: float = 0.2
    video_provider: str = "mock"
    real_video_max_tasks: int = 1
    real_video_max_concurrency: int = 1
    real_video_max_cost_usd: float = 1.0
    seedance_api_key: str | None = None
    seedance_base_url: str = "https://ark.ap-southeast.bytepluses.com/api/v3"
    seedance_model: str | None = None
    seedance_poll_interval_seconds: int = 10
    seedance_request_timeout_seconds: int = 30
    seedance_max_poll_minutes: int = 30

    def __post_init__(self) -> None:
        if self.ffmpeg_path == "ffmpeg":
            object.__setattr__(self, "ffmpeg_path", default_tool_path("ffmpeg"))
        if self.ffprobe_path == "ffprobe":
            object.__setattr__(self, "ffprobe_path", default_tool_path("ffprobe"))

    @classmethod
    def from_env(cls) -> AppConfig:
        project_root = Path.cwd()
        storage_dir = Path(
            os.getenv("STORAGE_ROOT", os.getenv("TK_VIDEO_STORAGE_DIR", "storage"))
        )
        database_path = Path(
            os.getenv("DATABASE_PATH", os.getenv("TK_VIDEO_DATABASE_PATH", "data/app.db"))
        )
        return cls(
            project_root=project_root,
            database_path=database_path,
            storage_dir=storage_dir,
            uploads_dir=storage_dir / "uploads",
            outputs_dir=storage_dir / "outputs",
            archives_dir=storage_dir / "archives",
            ffmpeg_path=os.getenv("TK_VIDEO_FFMPEG", default_tool_path("ffmpeg")),
            ffprobe_path=os.getenv("TK_VIDEO_FFPROBE", default_tool_path("ffprobe")),
            video_provider=os.getenv("VIDEO_PROVIDER", "mock"),
            real_video_max_tasks=int(os.getenv("REAL_VIDEO_MAX_TASKS", "1")),
            real_video_max_concurrency=int(os.getenv("REAL_VIDEO_MAX_CONCURRENCY", "1")),
            real_video_max_cost_usd=float(os.getenv("REAL_VIDEO_MAX_COST_USD", "1.00")),
            seedance_api_key=os.getenv("SEEDANCE_API_KEY") or None,
            seedance_base_url=os.getenv(
                "SEEDANCE_BASE_URL",
                "https://ark.ap-southeast.bytepluses.com/api/v3",
            ),
            seedance_model=os.getenv("SEEDANCE_MODEL") or None,
            seedance_poll_interval_seconds=int(
                os.getenv("SEEDANCE_POLL_INTERVAL_SECONDS", "10")
            ),
            seedance_request_timeout_seconds=int(
                os.getenv("SEEDANCE_REQUEST_TIMEOUT_SECONDS", "30")
            ),
            seedance_max_poll_minutes=int(os.getenv("SEEDANCE_MAX_POLL_MINUTES", "30")),
        )

    def ensure_directories(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.archives_dir.mkdir(parents=True, exist_ok=True)

    def seedance_config_status(self) -> str:
        return "Configured" if self.seedance_api_key and self.seedance_model else "Missing"

    def validate_seedance_config(self) -> None:
        missing = []
        if not self.seedance_api_key:
            missing.append("SEEDANCE_API_KEY")
        if not self.seedance_base_url:
            missing.append("SEEDANCE_BASE_URL")
        if not self.seedance_model:
            missing.append("SEEDANCE_MODEL")
        if missing:
            raise ValueError("Missing Seedance configuration: " + ", ".join(missing))

    def __repr__(self) -> str:
        redacted = self.__dict__.copy()
        if redacted.get("seedance_api_key"):
            redacted["seedance_api_key"] = "[REDACTED]"
        return f"AppConfig({redacted!r})"


def default_tool_path(tool_name: str) -> str:
    discovered = shutil.which(tool_name)
    if discovered:
        return discovered
    homebrew_path = Path("/opt/homebrew/bin") / tool_name
    if homebrew_path.exists():
        return str(homebrew_path)
    return tool_name
