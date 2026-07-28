import os
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

os.environ.setdefault("MYSQL_PASSWORD", "test")
os.environ.setdefault("STORAGE_ROOT", "./.test-storage")


@pytest.fixture
def workspace_tmp_path() -> Path:
    path = Path(__file__).resolve().parents[1] / ".test-artifacts" / uuid4().hex
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
