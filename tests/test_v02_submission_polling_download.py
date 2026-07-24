from __future__ import annotations

import json
from dataclasses import replace
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
        seedance_request_timeout_seconds=1,
    )


def make_seedance_task(
    *,
    task_id: str = "TASK",
    image_url: str = "https://example.com/first-frame.png",
    prompt: str = "prompt",
    duration_seconds: int = 5,
    aspect_ratio: str = "9:16",
) -> __import__("tk_video_generate.models", fromlist=["VideoTask"]).VideoTask:
    return __import__("tk_video_generate.models", fromlist=["VideoTask"]).VideoTask(
        id=task_id,
        batch_id="BATCH",
        name="Task",
        image_path="/local/preview.png",
        image_url=image_url,
        prompt=prompt,
        provider="byteplus_seedance",
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
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
    )


def test_seedance_submit_saves_provider_task_id_without_leaking_key(tmp_path, sample_image) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret-key"
        payload = json.loads(request.content)
        assert payload["content"][1]["image_url"]["url"] == "https://example.com/task-first-frame.png"
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
    task = replace(
        task,
        image_url="https://example.com/task-first-frame.png",
    )

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
    assert "task-first-frame.png" not in request_text


@pytest.mark.parametrize(
    ("payload", "expected_status", "expected_error"),
    [
        ({"id": "t", "status": "running", "progress": 50}, "running", None),
        (
            {"id": "t", "status": "succeeded", "content": {"video_url": "https://example.com/r.mp4"}},
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
    task = make_seedance_task()

    provider.submit(task, tmp_path / "out")

    assert seen == ["https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks"]


def test_seedance_payload_matches_official_contract(tmp_path) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["content_type"] = request.headers["Content-Type"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "remote-123"})

    transport = httpx.MockTransport(handler)
    config = seedance_config(tmp_path, transport)
    provider = BytePlusSeedanceProvider(
        config,
        client=httpx.Client(transport=transport, base_url=config.seedance_base_url, timeout=1),
    )
    task = make_seedance_task(
        image_url="https://assets.example.com/first-frame.png?signature=secret",
        prompt="A controlled slow camera movement around the product.",
        duration_seconds=5,
        aspect_ratio="9:16",
    )

    provider.submit(task, tmp_path / "out")

    payload = captured["payload"]
    assert captured["url"] == "https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks"
    assert captured["authorization"] == "Bearer secret-key"
    assert captured["content_type"] == "application/json"
    assert payload == {
        "model": "seedance-test",
        "content": [
            {"type": "text", "text": "A controlled slow camera movement around the product."},
            {
                "type": "image_url",
                "image_url": {"url": "https://assets.example.com/first-frame.png?signature=secret"},
                "role": "first_frame",
            },
        ],
        "duration": 5,
        "ratio": "9:16",
    }
    assert "/local/preview.png" not in json.dumps(payload)
    assert "secret-key" not in json.dumps(payload)


def test_seedance_requires_task_specific_https_image_url(tmp_path) -> None:
    config = seedance_config(tmp_path, httpx.MockTransport(lambda _request: httpx.Response(200)))
    provider = BytePlusSeedanceProvider(config)

    with pytest.raises(ProviderError, match="image_url"):
        provider.validate(make_seedance_task(image_url=""))
    with pytest.raises(ProviderError, match="HTTPS"):
        provider.validate(make_seedance_task(image_url="http://example.com/image.png"))


def test_task_specific_image_url_is_not_reused_between_tasks(tmp_path) -> None:
    config = seedance_config(tmp_path, httpx.MockTransport(lambda _request: httpx.Response(200)))
    provider = BytePlusSeedanceProvider(config)
    first = provider.request_payload(make_seedance_task(task_id="ONE", image_url="https://example.com/one.png"))
    second = provider.request_payload(make_seedance_task(task_id="TWO", image_url="https://example.com/two.png"))

    assert first["content"][1]["image_url"]["url"] == "https://example.com/one.png"
    assert second["content"][1]["image_url"]["url"] == "https://example.com/two.png"


def test_seedance_response_extracts_official_paths(tmp_path) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={
                "id": "remote-task",
                "status": "succeeded",
                "content": {"video_url": "https://example.com/result.mp4"},
            },
        )
    )
    config = seedance_config(tmp_path, transport)
    provider = BytePlusSeedanceProvider(
        config,
        client=httpx.Client(transport=transport, base_url=config.seedance_base_url, timeout=1),
    )

    result = provider.poll("remote-task")

    assert result.status == "succeeded"
    assert result.result_url == "https://example.com/result.mp4"


def test_redacted_request_does_not_log_full_url_or_api_key(tmp_path) -> None:
    config = seedance_config(tmp_path, httpx.MockTransport(lambda _request: httpx.Response(200)))
    provider = BytePlusSeedanceProvider(config)
    payload = provider.request_payload(
        make_seedance_task(image_url="https://assets.example.com/first-frame.png?signature=secret")
    )

    redacted = provider.redacted_payload(payload)
    rendered = json.dumps(redacted)

    assert "secret-key" not in rendered
    assert "signature=secret" not in rendered
    assert redacted["content"][1]["image_url"]["url"] == "[REDACTED_URL_PRESENT]"
