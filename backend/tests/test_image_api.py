import json
from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.image import get_image_dispatcher
from app.core.database import Base, get_db
from app.main import app
from app.models import GenerationTask, ImageGenerationTaskDetail, TaskReferenceImage
from app.models.image import ImageAspectRatio
from app.services.file_storage import FileStorageService
from app.services.image_generation import ImageBatchService
from tests.image_helpers import create_png_bytes


def create_test_client(
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
        "app.api.image.ImageBatchService",
        lambda: ImageBatchService(storage),
    )
    monkeypatch.setattr("app.api.files.FileStorageService", lambda: storage)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_image_dispatcher] = lambda: dispatched.append
    return TestClient(app), sessions, dispatched, storage


def test_create_image_batch_is_atomic_and_dispatches(workspace_tmp_path, monkeypatch) -> None:
    client, sessions, dispatched, _ = create_test_client(workspace_tmp_path, monkeypatch)
    payload = {
        "tasks": [
            {
                "prompt": "商品棚拍",
                "aspect_ratio": "3:4",
                "image_count": 2,
                "reference_images": ["reference.png"],
            },
            {
                "prompt": "纯文本生成",
                "aspect_ratio": "1:1",
                "image_count": 1,
                "reference_images": [],
            },
        ]
    }
    with client:
        response = client.post(
            "/api/image/batches",
            files=[
                ("payload", (None, json.dumps(payload), "application/json")),
                ("references_0", ("reference.png", create_png_bytes(), "image/png")),
            ],
        )
    app.dependency_overrides.clear()

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "PENDING"
    assert len(body["tasks"]) == 2
    assert dispatched == [item["task_id"] for item in body["tasks"]]
    with sessions() as session:
        details = session.scalars(select(ImageGenerationTaskDetail)).all()
        references = session.scalars(select(TaskReferenceImage)).all()
        assert [detail.aspect_ratio for detail in details] == [
            ImageAspectRatio.PORTRAIT_3_4,
            ImageAspectRatio.SQUARE_1_1,
        ]
        assert [detail.image_count for detail in details] == [2, 1]
        assert len(references) == 1
        assert not references[0].file_path.startswith(("C:", "/"))


def test_batch_rejects_invalid_count_and_ratio(workspace_tmp_path, monkeypatch) -> None:
    client, sessions, _, _ = create_test_client(workspace_tmp_path, monkeypatch)
    invalid_count = {
        "tasks": [
            {
                "prompt": "test",
                "aspect_ratio": "9:16",
                "image_count": 3,
                "reference_images": [],
            }
        ]
    }
    invalid_ratio = {
        "tasks": [
            {
                "prompt": "test",
                "aspect_ratio": "16:9",
                "image_count": 1,
                "reference_images": [],
            }
        ]
    }
    with client:
        count_response = client.post(
            "/api/image/batches",
            files={"payload": (None, json.dumps(invalid_count), "application/json")},
        )
        ratio_response = client.post(
            "/api/image/batches",
            files={"payload": (None, json.dumps(invalid_ratio), "application/json")},
        )
    app.dependency_overrides.clear()

    assert count_response.status_code == 422
    assert ratio_response.status_code == 422
    with sessions() as session:
        assert session.scalar(select(GenerationTask)) is None


def test_reference_upload_validates_real_image_content(workspace_tmp_path, monkeypatch) -> None:
    client, sessions, _, _ = create_test_client(workspace_tmp_path, monkeypatch)
    payload = {
        "tasks": [
            {
                "prompt": "test",
                "aspect_ratio": "9:16",
                "image_count": 1,
                "reference_images": [],
            }
        ]
    }
    with client:
        created = client.post(
            "/api/image/batches",
            files={"payload": (None, json.dumps(payload), "application/json")},
        ).json()
        task_id = created["tasks"][0]["task_id"]
        invalid = client.post(
            f"/api/image/tasks/{task_id}/references",
            files={"file": ("fake.png", b"not-an-image", "image/png")},
        )
        valid = client.post(
            f"/api/image/tasks/{task_id}/references",
            files={"file": ("real.png", create_png_bytes(), "image/png")},
        )
    app.dependency_overrides.clear()

    assert invalid.status_code == 422
    assert invalid.json()["code"] == "INVALID_IMAGE_CONTENT"
    assert valid.status_code == 201
    with sessions() as session:
        assert len(session.scalars(select(TaskReferenceImage)).all()) == 1


# ── 图片提示词长度校验 ──


def test_image_prompt_length_1_passes(workspace_tmp_path, monkeypatch) -> None:
    client, _, _, _ = create_test_client(workspace_tmp_path, monkeypatch)
    payload = {
        "tasks": [{"prompt": "a", "aspect_ratio": "9:16", "image_count": 1, "reference_images": []}]
    }
    with client:
        response = client.post(
            "/api/image/batches",
            files={"payload": (None, json.dumps(payload), "application/json")},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 201, response.text


def test_image_prompt_length_1000_passes(workspace_tmp_path, monkeypatch) -> None:
    client, _, _, _ = create_test_client(workspace_tmp_path, monkeypatch)
    payload = {
        "tasks": [{"prompt": "a" * 1000, "aspect_ratio": "9:16", "image_count": 1, "reference_images": []}]
    }
    with client:
        response = client.post(
            "/api/image/batches",
            files={"payload": (None, json.dumps(payload), "application/json")},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 201, response.text


def test_image_prompt_length_10000_passes(workspace_tmp_path, monkeypatch) -> None:
    client, _, _, _ = create_test_client(workspace_tmp_path, monkeypatch)
    payload = {
        "tasks": [{"prompt": "a" * 10000, "aspect_ratio": "9:16", "image_count": 1, "reference_images": []}]
    }
    with client:
        response = client.post(
            "/api/image/batches",
            files={"payload": (None, json.dumps(payload), "application/json")},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 201, response.text


def test_image_prompt_length_10001_rejected(workspace_tmp_path, monkeypatch) -> None:
    client, sessions, _, _ = create_test_client(workspace_tmp_path, monkeypatch)
    payload = {
        "tasks": [{"prompt": "a" * 10001, "aspect_ratio": "9:16", "image_count": 1, "reference_images": []}]
    }
    with client:
        response = client.post(
            "/api/image/batches",
            files={"payload": (None, json.dumps(payload), "application/json")},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 422
    with sessions() as session:
        assert session.scalar(select(GenerationTask)) is None


def test_image_prompt_empty_rejected(workspace_tmp_path, monkeypatch) -> None:
    client, sessions, _, _ = create_test_client(workspace_tmp_path, monkeypatch)
    payload = {
        "tasks": [{"prompt": "", "aspect_ratio": "9:16", "image_count": 1, "reference_images": []}]
    }
    with client:
        response = client.post(
            "/api/image/batches",
            files={"payload": (None, json.dumps(payload), "application/json")},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 422
    with sessions() as session:
        assert session.scalar(select(GenerationTask)) is None


def test_image_prompt_whitespace_rejected(workspace_tmp_path, monkeypatch) -> None:
    client, sessions, _, _ = create_test_client(workspace_tmp_path, monkeypatch)
    payload = {
        "tasks": [{"prompt": "   ", "aspect_ratio": "9:16", "image_count": 1, "reference_images": []}]
    }
    with client:
        response = client.post(
            "/api/image/batches",
            files={"payload": (None, json.dumps(payload), "application/json")},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 422
    with sessions() as session:
        assert session.scalar(select(GenerationTask)) is None


def test_image_batch_any_prompt_over_limit_rejects_whole_batch(
    workspace_tmp_path, monkeypatch
) -> None:
    client, sessions, _, _ = create_test_client(workspace_tmp_path, monkeypatch)
    payload = {
        "tasks": [
            {"prompt": "valid prompt", "aspect_ratio": "9:16", "image_count": 1, "reference_images": []},
            {"prompt": "a" * 10001, "aspect_ratio": "9:16", "image_count": 1, "reference_images": []},
        ]
    }
    with client:
        response = client.post(
            "/api/image/batches",
            files={"payload": (None, json.dumps(payload), "application/json")},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 422
    with sessions() as session:
        assert session.scalar(select(GenerationTask)) is None
