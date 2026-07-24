from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from conftest import create_batch, make_upload

from tk_video_generate.config import AppConfig
from tk_video_generate.enums import TaskStatus
from tk_video_generate.providers.base import ProviderError
from tk_video_generate.providers.byteplus_seedance import BytePlusSeedanceProvider
from tk_video_generate.services.workbench_service import WorkbenchService


def seedance_config(tmp_path: Path, transport: httpx.MockTransport) -> AppConfig:
    storage = tmp_path / "storage"
    return AppConfig(
        project_root=tmp_path,
        database_path=tmp_path / "data/app.db",
        storage_dir=storage,
        uploads_dir=storage / "uploads",
        outputs_dir=storage / "outputs",
        archives_dir=storage / "archives",
        seedance_api_key="secret-key",
        seedance_model="seedance-test",
        seedance_image_url="https://example.com/first-frame.png",
        seedance_request_timeout_seconds=1,
    )


def test_seedance_submit_saves_provider_task_id_without_leaking_key(tmp_path, sample_image) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret-key"
        return httpx.Response(200, json={"id": "remote-123", "status": "queued"})

    transport = httpx.MockTransport(handler)
    config = seedance_config(tmp_path, transport)
    provider = BytePlusSeedanceProvider(
        config,
        client=httpx.Client(
            transport=transport,
            base_url=config.seedance_base_url,
            timeout=1,
        ),
    )
    service = WorkbenchService(config)
    batch = create_batch(service, sample_image, batch_id="BATCH_SUBMIT_SAVE")
    task = service.list_tasks(batch.id)[0]

    submission = provider.submit(task, config.outputs_dir / task.batch_id / task.id)
    service.repository.mark_submitted(
        task.id,
        submission.provider_task_id,
        config.outputs_dir / task.batch_id / task.id / "provider_submit_response.json",
        config.outputs_dir / task.batch_id / task.id / "request.json",
        "2026-07-24T00:00:00+00:00",
        "2026-07-24T00:00:10+00:00",
    )
    persisted = service.get_task(task.id)
    request_text = (config.outputs_dir / task.batch_id / task.id / "request.json").read_text()

    assert persisted.provider_task_id == "remote-123"
    assert "secret-key" not in request_text


@pytest.mark.parametrize(
    ("payload", "expected_status", "expected_error"),
    [
        ({"id": "t", "status": "running", "progress": 50}, "running", None),
        (
            {"id": "t", "status": "succeeded", "result_url": "https://example.com/r.mp4"},
            "succeeded",
            None,
        ),
        ({"id": "t", "status": "failed", "error": {"code": "X", "message": "bad"}}, "failed", "X"),
        ({"id": "t", "status": "mystery"}, "failed", "PROVIDER_UNKNOWN_STATUS"),
        ({"id": "t", "status": "succeeded"}, "failed", "RESULT_URL_MISSING"),
    ],
)
def test_seedance_poll_status_mapping(tmp_path, payload, expected_status, expected_error) -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    config = seedance_config(tmp_path, transport)
    provider = BytePlusSeedanceProvider(
        config,
        client=httpx.Client(transport=transport, base_url=config.seedance_base_url, timeout=1),
    )

    result = provider.poll("remote-task")

    assert result.status == expected_status
    assert result.error_code == expected_error


def test_transient_poll_error_does_not_resubmit(tmp_path) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    transport = httpx.MockTransport(handler)
    config = seedance_config(tmp_path, transport)
    provider = BytePlusSeedanceProvider(
        config,
        client=httpx.Client(transport=transport, base_url=config.seedance_base_url, timeout=1),
    )

    with pytest.raises(ProviderError, match="status 429") as exc_info:
        provider.poll("remote-task")

    assert exc_info.value.code == "PROVIDER_RATE_LIMITED"
    assert calls == ["GET"]


def test_seedance_download_rejects_empty_file(tmp_path) -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=b""))
    config = seedance_config(tmp_path, transport)
    provider = BytePlusSeedanceProvider(
        config,
        client=httpx.Client(transport=transport, base_url=config.seedance_base_url, timeout=1),
    )

    with pytest.raises(ProviderError, match="empty"):
        provider.download("https://example.com/empty.mp4", tmp_path / "empty.mp4")


def test_seedance_mode_service_boundary_requires_single_paid_confirmed_task(
    app_config,
    image_upload_bytes,
) -> None:
    service = WorkbenchService(app_config)

    with pytest.raises(ValueError, match="confirmation"):
        service.create_confirmed_batch(
            batch_id="BATCH_REAL_BAD_CONFIRM",
            batch_name="real",
            uploaded_files=[make_upload(image_upload_bytes)],
            prompts=["prompt"],
            duration_seconds=3,
            aspect_ratio="9:16",
            concurrency_limit=1,
            confirmation="CONFIRM BATCH_REAL_BAD_CONFIRM",
            expected_confirmation="CONFIRM REAL BATCH_REAL_BAD_CONFIRM",
            provider_name="byteplus_seedance",
            real_api_confirmed=True,
            maximum_cost_usd=1.0,
        )

    with pytest.raises(ValueError, match="Seedance mode allows exactly one task"):
        service.create_confirmed_batch(
            batch_id="BATCH_REAL_TOO_MANY",
            batch_name="real",
            uploaded_files=[make_upload(image_upload_bytes), make_upload(image_upload_bytes)],
            prompts=["one", "two"],
            duration_seconds=3,
            aspect_ratio="9:16",
            concurrency_limit=1,
            confirmation="CONFIRM REAL BATCH_REAL_TOO_MANY",
            expected_confirmation="CONFIRM REAL BATCH_REAL_TOO_MANY",
            provider_name="byteplus_seedance",
            real_api_confirmed=True,
            maximum_cost_usd=1.0,
        )

    with pytest.raises(ValueError, match="Paid API confirmation"):
        service.create_confirmed_batch(
            batch_id="BATCH_REAL_UNPAID",
            batch_name="real",
            uploaded_files=[make_upload(image_upload_bytes)],
            prompts=["prompt"],
            duration_seconds=3,
            aspect_ratio="9:16",
            concurrency_limit=1,
            confirmation="CONFIRM REAL BATCH_REAL_UNPAID",
            expected_confirmation="CONFIRM REAL BATCH_REAL_UNPAID",
            provider_name="byteplus_seedance",
            real_api_confirmed=False,
            maximum_cost_usd=1.0,
        )


def test_tests_use_mock_transport_not_real_network(tmp_path) -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"id": "remote", "status": "queued"})

    transport = httpx.MockTransport(handler)
    config = seedance_config(tmp_path, transport)
    provider = BytePlusSeedanceProvider(
        config,
        client=httpx.Client(transport=transport, base_url=config.seedance_base_url, timeout=1),
    )
    raw_task = {
        "id": "TASK",
        "batch_id": "BATCH",
        "name": "Task",
        "image_path": "image.png",
        "prompt": "prompt",
        "provider": "byteplus_seedance",
        "duration_seconds": 3,
        "aspect_ratio": "9:16",
        "status": TaskStatus.SUBMITTING,
        "progress": 0,
        "provider_task_id": None,
        "output_video_path": None,
        "request_json_path": None,
        "result_json_path": None,
        "retry_count": 0,
        "error_code": None,
        "error_message": None,
        "created_at": "now",
        "updated_at": "now",
        "completed_at": None,
    }
    task = __import__("tk_video_generate.models", fromlist=["VideoTask"]).VideoTask(**raw_task)

    provider.submit(task, tmp_path / "out")

    assert seen == ["https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks"]
