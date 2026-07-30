import json
from collections.abc import Generator

import pytest
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


def test_video_batch_persists_five_reference_positions_and_normalizes_prompt(
    workspace_tmp_path, monkeypatch
) -> None:
    client, sessions, _, _ = create_video_test_client(workspace_tmp_path, monkeypatch)
    filenames = [f"reference-{index}.png" for index in range(1, 6)]
    payload = {
        "tasks": [
            {
                "prompt": "让@图片1靠近@图片5",
                "reference_mode": "REFERENCE",
                "resolution": "720P",
                "aspect_ratio": "9:16",
                "duration_mode": "SMART",
                "reference_images": filenames,
            }
        ]
    }
    files = [("payload", (None, json.dumps(payload), "application/json"))]
    files.extend(
        ("references_0", (filename, create_png_bytes(), "image/png"))
        for filename in filenames
    )

    with client:
        response = client.post("/api/video/batches", files=files)
    app.dependency_overrides.clear()

    assert response.status_code == 201, response.text
    with sessions() as session:
        task = session.scalar(select(GenerationTask))
        assert task is not None
        assert task.prompt == "让图片1靠近图片5"
        references = session.scalars(
            select(TaskReferenceImage).order_by(TaskReferenceImage.position)
        ).all()
        assert [reference.position for reference in references] == list(range(5))
        assert [reference.file_name for reference in references] == filenames


@pytest.mark.parametrize(
    "prompt",
    [
        "请参考图片1，让图片2中的人物也xxx",
        "请参考@图片1，让图片2中的人物也xxx",
        "请参考@图片1，让@图片2中的人物也xxx",
    ],
)
def test_video_batch_core_prompt_scenarios_store_the_same_normalized_prompt(
    workspace_tmp_path, monkeypatch, prompt: str
) -> None:
    client, sessions, _, _ = create_video_test_client(workspace_tmp_path, monkeypatch)
    filenames = ["girl.png", "product.png"]
    payload = {
        "tasks": [
            {
                "prompt": prompt,
                "reference_mode": "REFERENCE",
                "resolution": "720P",
                "aspect_ratio": "9:16",
                "duration_mode": "SMART",
                "reference_images": filenames,
            }
        ]
    }
    files = [("payload", (None, json.dumps(payload), "application/json"))]
    files.extend(
        ("references_0", (filename, create_png_bytes(), "image/png"))
        for filename in filenames
    )

    with client:
        response = client.post("/api/video/batches", files=files)
    app.dependency_overrides.clear()

    assert response.status_code == 201, response.text
    with sessions() as session:
        task = session.scalar(select(GenerationTask))
        assert task is not None
        assert task.prompt == "请参考图片1，让图片2中的人物也xxx"
        references = session.scalars(
            select(TaskReferenceImage).order_by(TaskReferenceImage.position)
        ).all()
        assert [(item.position, item.file_name) for item in references] == [
            (0, "girl.png"),
            (1, "product.png"),
        ]


def test_video_batch_rejects_reference_above_uploaded_image_count(
    workspace_tmp_path, monkeypatch
) -> None:
    client, sessions, _, _ = create_video_test_client(workspace_tmp_path, monkeypatch)
    payload = {
        "tasks": [
            {
                "prompt": "让@图片6进入镜头",
                "reference_mode": "REFERENCE",
                "resolution": "720P",
                "aspect_ratio": "9:16",
                "duration_mode": "SMART",
                "reference_images": ["only.png"],
            }
        ]
    }

    with client:
        response = client.post(
            "/api/video/batches",
            files=[
                ("payload", (None, json.dumps(payload), "application/json")),
                ("references_0", ("only.png", create_png_bytes(), "image/png")),
            ],
        )
    app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_VIDEO_IMAGE_REFERENCE"
    with sessions() as session:
        assert session.scalar(select(GenerationTask)) is None


# ── 视频提示词长度校验 ──


def test_video_prompt_length_1_passes(workspace_tmp_path, monkeypatch) -> None:
    client, _, _, _ = create_video_test_client(workspace_tmp_path, monkeypatch)
    payload = {
        "tasks": [{"prompt": "a", "reference_mode": "REFERENCE", "resolution": "720P",
                     "aspect_ratio": "9:16", "duration_mode": "SMART", "reference_images": []}]
    }
    with client:
        response = client.post(
            "/api/video/batches",
            files={"payload": (None, json.dumps(payload), "application/json")},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 201, response.text


def test_video_prompt_length_1000_passes(workspace_tmp_path, monkeypatch) -> None:
    client, _, _, _ = create_video_test_client(workspace_tmp_path, monkeypatch)
    payload = {
        "tasks": [{"prompt": "a" * 1000, "reference_mode": "REFERENCE", "resolution": "720P",
                     "aspect_ratio": "9:16", "duration_mode": "SMART", "reference_images": []}]
    }
    with client:
        response = client.post(
            "/api/video/batches",
            files={"payload": (None, json.dumps(payload), "application/json")},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 201, response.text


def test_video_prompt_length_10000_passes(workspace_tmp_path, monkeypatch) -> None:
    client, _, _, _ = create_video_test_client(workspace_tmp_path, monkeypatch)
    payload = {
        "tasks": [{"prompt": "a" * 10000, "reference_mode": "REFERENCE", "resolution": "720P",
                     "aspect_ratio": "9:16", "duration_mode": "SMART", "reference_images": []}]
    }
    with client:
        response = client.post(
            "/api/video/batches",
            files={"payload": (None, json.dumps(payload), "application/json")},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 201, response.text


def test_video_prompt_length_10001_rejected(workspace_tmp_path, monkeypatch) -> None:
    client, sessions, _, _ = create_video_test_client(workspace_tmp_path, monkeypatch)
    payload = {
        "tasks": [{"prompt": "a" * 10001, "reference_mode": "REFERENCE", "resolution": "720P",
                     "aspect_ratio": "9:16", "duration_mode": "SMART", "reference_images": []}]
    }
    with client:
        response = client.post(
            "/api/video/batches",
            files={"payload": (None, json.dumps(payload), "application/json")},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 422
    with sessions() as session:
        assert session.scalar(select(GenerationTask)) is None


def test_video_prompt_empty_rejected(workspace_tmp_path, monkeypatch) -> None:
    client, sessions, _, _ = create_video_test_client(workspace_tmp_path, monkeypatch)
    payload = {
        "tasks": [{"prompt": "", "reference_mode": "REFERENCE", "resolution": "720P",
                     "aspect_ratio": "9:16", "duration_mode": "SMART", "reference_images": []}]
    }
    with client:
        response = client.post(
            "/api/video/batches",
            files={"payload": (None, json.dumps(payload), "application/json")},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 422
    with sessions() as session:
        assert session.scalar(select(GenerationTask)) is None


def test_video_prompt_whitespace_rejected(workspace_tmp_path, monkeypatch) -> None:
    client, sessions, _, _ = create_video_test_client(workspace_tmp_path, monkeypatch)
    payload = {
        "tasks": [{"prompt": "   ", "reference_mode": "REFERENCE", "resolution": "720P",
                     "aspect_ratio": "9:16", "duration_mode": "SMART", "reference_images": []}]
    }
    with client:
        response = client.post(
            "/api/video/batches",
            files={"payload": (None, json.dumps(payload), "application/json")},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 422
    with sessions() as session:
        assert session.scalar(select(GenerationTask)) is None


def test_video_batch_any_prompt_over_limit_rejects_whole_batch(
    workspace_tmp_path, monkeypatch
) -> None:
    client, sessions, _, _ = create_video_test_client(workspace_tmp_path, monkeypatch)
    payload = {
        "tasks": [
            {"prompt": "valid prompt", "reference_mode": "REFERENCE", "resolution": "720P",
             "aspect_ratio": "9:16", "duration_mode": "SMART", "reference_images": []},
            {"prompt": "a" * 10001, "reference_mode": "REFERENCE", "resolution": "720P",
             "aspect_ratio": "9:16", "duration_mode": "SMART", "reference_images": []},
        ]
    }
    with client:
        response = client.post(
            "/api/video/batches",
            files={"payload": (None, json.dumps(payload), "application/json")},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 422
    with sessions() as session:
        assert session.scalar(select(GenerationTask)) is None
