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

    def __post_init__(self) -> None:
        if self.ffmpeg_path == "ffmpeg":
            object.__setattr__(self, "ffmpeg_path", default_tool_path("ffmpeg"))
        if self.ffprobe_path == "ffprobe":
            object.__setattr__(self, "ffprobe_path", default_tool_path("ffprobe"))

    @classmethod
    def from_env(cls) -> AppConfig:
        project_root = Path.cwd()
        storage_dir = Path(os.getenv("TK_VIDEO_STORAGE_DIR", "storage"))
        database_path = Path(os.getenv("TK_VIDEO_DATABASE_PATH", "data/app.db"))
        return cls(
            project_root=project_root,
            database_path=database_path,
            storage_dir=storage_dir,
            uploads_dir=storage_dir / "uploads",
            outputs_dir=storage_dir / "outputs",
            archives_dir=storage_dir / "archives",
            ffmpeg_path=os.getenv("TK_VIDEO_FFMPEG", default_tool_path("ffmpeg")),
            ffprobe_path=os.getenv("TK_VIDEO_FFPROBE", default_tool_path("ffprobe")),
        )

    def ensure_directories(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.archives_dir.mkdir(parents=True, exist_ok=True)


def default_tool_path(tool_name: str) -> str:
    discovered = shutil.which(tool_name)
    if discovered:
        return discovered
    homebrew_path = Path("/opt/homebrew/bin") / tool_name
    if homebrew_path.exists():
        return str(homebrew_path)
    return tool_name
