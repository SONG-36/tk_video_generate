import json
from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.video import get_video_dispatcher
from app.core.database import Base, get_db
from app.main import app
from app.models import GenerationTask, TaskReferenceImage, VideoGenerationTaskDetail
from app.models.video import (
    VideoAspectRatio,
    VideoDurationMode,
    VideoReferenceMode,
    VideoResolution,
)
from app.services.file_storage import FileStorageService
from app.services.video_generation import VideoBatchService
from tests.image_helpers import create_png_bytes


def create_video_test_client(
    tmp_path, monkeypatch
) -> tuple[TestClient, sessionmaker[Session], list[int], FileStorageService]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    dispatched: list[int] = []

    def override_db() -> Generator[Session, None, None]:
        with sessions() as session:
            yield session

    storage = FileStorageService(tmp_path)
    monkeypatch.setattr(
        "app.api.video.VideoBatchService",
        lambda: VideoBatchService(storage),
    )
    monkeypatch.setattr("app.api.files.FileStorageService", lambda: storage)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_video_dispatcher] = lambda: dispatched.append
    return TestClient(app), sessions, dispatched, storage


def test_create_video_batch_persists_parameters_and_dispatches(
    workspace_tmp_path, monkeypatch
) -> None:
    client, sessions, dispatched, _ = create_video_test_client(
        workspace_tmp_path, monkeypatch
    )
    payload = {
        "tasks": [
            {
                "prompt": "镜头缓慢推进",
                "reference_mode": "FIRST_FRAME",
                "resolution": "720P",
                "aspect_ratio": "9:16",
                "duration_mode": "FIXED",
                "fixed_duration": 10,
                "output_sound": True,
                "reference_images": ["first.png"],
            },
            {
                "prompt": "智能生成",
                "reference_mode": "REFERENCE",
                "resolution": "480P",
                "aspect_ratio": "16:9",
                "duration_mode": "SMART",
                "fixed_duration": None,
                "output_sound": False,
                "reference_images": [],
            },
        ]
    }
    with client:
        response = client.post(
            "/api/video/batches",
            files=[
                ("payload", (None, json.dumps(payload), "application/json")),
                ("references_0", ("first.png", create_png_bytes(), "image/png")),
            ],
        )
    app.dependency_overrides.clear()

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "PENDING"
    assert dispatched == [item["task_id"] for item in body["tasks"]]
    with sessions() as session:
        details = session.scalars(select(VideoGenerationTaskDetail)).all()
        assert details[0].reference_mode == VideoReferenceMode.FIRST_FRAME
        assert details[0].resolution == VideoResolution.P720
        assert details[0].aspect_ratio == VideoAspectRatio.PORTRAIT_9_16
        assert details[0].duration_mode == VideoDurationMode.FIXED
        assert details[0].fixed_duration == 10
        assert details[0].output_sound is True
        assert details[1].fixed_duration is None
        assert len(session.scalars(select(TaskReferenceImage)).all()) == 1


def test_video_batch_rejects_invalid_duration_and_missing_first_frame(
    workspace_tmp_path, monkeypatch
) -> None:
    client, sessions, _, _ = create_video_test_client(workspace_tmp_path, monkeypatch)
    invalid_duration = {
        "tasks": [
            {
                "prompt": "test",
                "reference_mode": "REFERENCE",
                "resolution": "720P",
                "aspect_ratio": "9:16",
                "duration_mode": "FIXED",
                "fixed_duration": 3,
                "reference_images": [],
            }
        ]
    }
    missing_frame = {
        "tasks": [
            {
                "prompt": "test",
                "reference_mode": "FIRST_FRAME",
                "resolution": "720P",
                "aspect_ratio": "9:16",
                "duration_mode": "SMART",
                "reference_images": [],
            }
        ]
    }
    with client:
        duration_response = client.post(
            "/api/video/batches",
            files={"payload": (None, json.dumps(invalid_duration), "application/json")},
        )
        frame_response = client.post(
            "/api/video/batches",
            files={"payload": (None, json.dumps(missing_frame), "application/json")},
        )
    app.dependency_overrides.clear()

    assert duration_response.status_code == 422
    assert frame_response.status_code == 422
    with sessions() as session:
        assert session.scalar(select(GenerationTask)) is None


def test_video_reference_upload_validates_image_content(
    workspace_tmp_path, monkeypatch
) -> None:
    client, _, _, _ = create_video_test_client(workspace_tmp_path, monkeypatch)
    payload = {
        "tasks": [
            {
                "prompt": "reference test",
                "reference_mode": "REFERENCE",
                "resolution": "720P",
                "aspect_ratio": "9:16",
                "duration_mode": "SMART",
                "reference_images": [],
            }
        ]
    }
    with client:
        created = client.post(
            "/api/video/batches",
            files={"payload": (None, json.dumps(payload), "application/json")},
        ).json()
        task_id = created["tasks"][0]["task_id"]
        invalid = client.post(
            f"/api/video/tasks/{task_id}/references",
            files={"file": ("fake.png", b"not-an-image", "image/png")},
        )
        valid = client.post(
            f"/api/video/tasks/{task_id}/references",
            files={"file": ("real.png", create_png_bytes(), "image/png")},
        )
    app.dependency_overrides.clear()

    assert invalid.status_code == 422
    assert invalid.json()["code"] == "INVALID_IMAGE_CONTENT"
    assert valid.status_code == 201
