from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from tk_video_generate.config import AppConfig


@pytest.fixture
def app_config(tmp_path: Path) -> AppConfig:
    storage_dir = tmp_path / "storage"
    return AppConfig(
        project_root=tmp_path,
        database_path=tmp_path / "data" / "app.db",
        storage_dir=storage_dir,
        uploads_dir=storage_dir / "uploads",
        outputs_dir=storage_dir / "outputs",
        archives_dir=storage_dir / "archives",
    )


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    path = tmp_path / "first_frame.png"
    Image.new("RGB", (160, 90), color=(30, 90, 160)).save(path)
    return path
