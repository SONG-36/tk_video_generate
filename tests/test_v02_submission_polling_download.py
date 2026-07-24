from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from conftest import make_upload

from tk_video_generate.config import AppConfig
from tk_video_generate.enums import TaskStatus
from tk_video_generate.models import VideoTask
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
        seedance_request_timeout_seconds=1,
    )


def test_seedance_submit_saves_provider_task_id_without_leaking_key(tmp_path, sample_image) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret-key"
        assert request.url.path == "/api/v3/contents/generations/tasks"
        payload = json.loads(request.content)
        assert payload["model"] == "seedance-test"
        assert payload["content"][0] == {"type": "text", "text": "normal prompt"}
        assert payload["content"][1] == {
            "type": "image_url",
            "image_url": {"url": "https://task-one.example.com/first-frame.png"},
            "role": "first_frame",
        }
        assert payload["duration"] == 3
        assert payload["ratio"] == "16:9"
        assert "secret-key" not in str(payload)
        assert str(sample_image) not in str(payload)
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
    batch = service.create_batch_from_paths(
        batch_id="BATCH_SUBMIT_SAVE",
        batch_name="BATCH_SUBMIT_SAVE",
        image_paths=[sample_image],
        prompts=["normal prompt"],
        duration_seconds=3,
        aspect_ratio="16:9",
        concurrency_limit=1,
        provider_name="byteplus_seedance",
        image_urls=["https://task-one.example.com/first-frame.png"],
    )
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
    assert "https://task-one.example.com/first-frame.png" not in request_text
    assert "task-one.example.com" in request_text


@pytest.mark.parametrize(
    ("payload", "expected_status", "expected_error"),
    [
        ({"id": "t", "status": "running", "progress": 50}, "running", None),
        (
            {
                "id": "t",
                "status": "succeeded",
                "content": {"video_url": "https://example.com/r.mp4"},
            },
            "succeeded",
            None,
        ),
        ({"id": "t", "status": "failed", "error": {"code": "X", "message": "bad"}}, "failed", "X"),
        ({"id": "t", "status": "expired"}, "failed", None),
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
            image_urls=["https://example.com/first-frame.png"],
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
            image_urls=[
                "https://example.com/first-frame-a.png",
                "https://example.com/first-frame-b.png",
            ],
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
            image_urls=["https://example.com/first-frame.png"],
        )


def test_seedance_mode_requires_task_specific_https_image_url(
    app_config,
    image_upload_bytes,
) -> None:
    config = AppConfig(
        project_root=app_config.project_root,
        database_path=app_config.database_path,
        storage_dir=app_config.storage_dir,
        uploads_dir=app_config.uploads_dir,
        outputs_dir=app_config.outputs_dir,
        archives_dir=app_config.archives_dir,
        seedance_api_key="secret-key",
        seedance_model="seedance-test",
    )
    service = WorkbenchService(config)

    with pytest.raises(ValueError, match="task-specific image_url"):
        service.create_confirmed_batch(
            batch_id="BATCH_REAL_NO_URL",
            batch_name="real",
            uploaded_files=[make_upload(image_upload_bytes)],
            prompts=["prompt"],
            duration_seconds=3,
            aspect_ratio="9:16",
            concurrency_limit=1,
            confirmation="CONFIRM REAL BATCH_REAL_NO_URL",
            expected_confirmation="CONFIRM REAL BATCH_REAL_NO_URL",
            provider_name="byteplus_seedance",
            real_api_confirmed=True,
            maximum_cost_usd=1.0,
            image_urls=[],
        )

    with pytest.raises(ValueError, match="HTTPS URL"):
        service.create_confirmed_batch(
            batch_id="BATCH_REAL_HTTP_URL",
            batch_name="real",
            uploaded_files=[make_upload(image_upload_bytes)],
            prompts=["prompt"],
            duration_seconds=3,
            aspect_ratio="9:16",
            concurrency_limit=1,
            confirmation="CONFIRM REAL BATCH_REAL_HTTP_URL",
            expected_confirmation="CONFIRM REAL BATCH_REAL_HTTP_URL",
            provider_name="byteplus_seedance",
            real_api_confirmed=True,
            maximum_cost_usd=1.0,
            image_urls=["http://example.com/first-frame.png"],
        )


def test_seedance_payload_uses_each_task_image_url(tmp_path) -> None:
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_urls.append(payload["content"][1]["image_url"]["url"])
        return httpx.Response(200, json={"id": f"remote-{len(seen_urls)}"})

    transport = httpx.MockTransport(handler)
    config = seedance_config(tmp_path, transport)
    provider = BytePlusSeedanceProvider(
        config,
        client=httpx.Client(transport=transport, base_url=config.seedance_base_url, timeout=1),
    )

    provider.submit(
        _seedance_task("TASK_A", "https://a.example.com/first-frame.png"),
        tmp_path / "a",
    )
    provider.submit(
        _seedance_task("TASK_B", "https://b.example.com/first-frame.png"),
        tmp_path / "b",
    )

    assert seen_urls == [
        "https://a.example.com/first-frame.png",
        "https://b.example.com/first-frame.png",
    ]


def test_seedance_extracts_official_task_id_and_result_url_paths(tmp_path) -> None:
    responses = iter(
        [
            httpx.Response(200, json={"id": "official-task-id"}),
            httpx.Response(
                200,
                json={
                    "id": "official-task-id",
                    "status": "succeeded",
                    "content": {"video_url": "https://cdn.example.com/result.mp4"},
                },
            ),
        ]
    )
    transport = httpx.MockTransport(lambda _request: next(responses))
    config = seedance_config(tmp_path, transport)
    provider = BytePlusSeedanceProvider(
        config,
        client=httpx.Client(transport=transport, base_url=config.seedance_base_url, timeout=1),
    )

    submission = provider.submit(
        _seedance_task("TASK_ID", "https://example.com/first-frame.png"),
        tmp_path / "submit",
    )
    poll = provider.poll("official-task-id")

    assert submission.provider_task_id == "official-task-id"
    assert poll.status == "succeeded"
    assert poll.result_url == "https://cdn.example.com/result.mp4"


def test_real_seedance_smoke_dry_run_is_redacted(tmp_path) -> None:
    output_json = tmp_path / "dry-run.json"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/real_seedance_smoke.py",
            "--dry-run",
            "--image-url",
            "https://example.com/private-token/first-frame.png",
            "--prompt",
            "A controlled slow camera movement around the product.",
            "--output-json",
            str(output_json),
        ],
        check=False,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    rendered = output_json.read_text(encoding="utf-8")
    assert "private-token" not in rendered
    assert "https://example.com/private-token/first-frame.png" not in result.stdout
    assert "image_input_type=https_url" in result.stdout
    assert "image_url_host=example.com" in result.stdout
    assert "Bearer [REDACTED]" in rendered


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
        "image_url": "https://example.com/first-frame.png",
    }
    task = __import__("tk_video_generate.models", fromlist=["VideoTask"]).VideoTask(**raw_task)

    provider.submit(task, tmp_path / "out")

    assert seen == ["https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks"]


def _seedance_task(task_id: str, image_url: str) -> VideoTask:
    return VideoTask(
        id=task_id,
        batch_id="BATCH",
        name="Task",
        image_path="/local/preview.png",
        prompt="prompt",
        provider="byteplus_seedance",
        model="seedance-test",
        duration_seconds=5,
        aspect_ratio="9:16",
        status=TaskStatus.SUBMITTING,
        progress=0,
        provider_task_id=None,
        output_video_path=None,
        request_json_path=None,
        result_json_path=None,
        retry_count=0,
        error_code=None,
        error_message=None,
        created_at="now",
        updated_at="now",
        completed_at=None,
        image_url=image_url,
    )
