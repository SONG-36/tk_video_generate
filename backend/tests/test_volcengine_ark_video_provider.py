import asyncio
import base64
import json
import logging
from pathlib import Path

import httpx
import pytest

from app.core.exceptions import AppError
from app.models.video import (
    VideoAspectRatio,
    VideoDurationMode,
    VideoModel,
    VideoOutputFormat,
    VideoReferenceMode,
    VideoResolution,
)
from app.providers.video.base import VideoGenerationRequest
from app.providers.video.mock import MOCK_MP4
from app.providers.video.volcengine_ark_provider import (
    VolcengineArkVideoGenerationProvider,
)
from tests.image_helpers import create_png_bytes


async def no_sleep(_: float) -> None:
    return None


async def generate_and_close_client(
    provider: VolcengineArkVideoGenerationProvider,
    request: VideoGenerationRequest,
    client: httpx.AsyncClient,
):
    try:
        return await provider.generate(request)
    finally:
        await client.aclose()


def make_request(
    *,
    reference_mode: VideoReferenceMode = VideoReferenceMode.REFERENCE,
    duration_mode: VideoDurationMode = VideoDurationMode.FIXED,
    fixed_duration: int | None = 5,
    output_sound: bool = True,
    reference_paths: list[Path] | None = None,
) -> VideoGenerationRequest:
    return VideoGenerationRequest(
        task_id=1,
        prompt="A cat walking through neon rain",
        reference_mode=reference_mode,
        resolution=VideoResolution.P720,
        aspect_ratio=VideoAspectRatio.PORTRAIT_9_16,
        duration_mode=duration_mode,
        fixed_duration=fixed_duration,
        output_sound=output_sound,
        model=VideoModel.SEEDANCE_2_0_MINI.value,
        output_format=VideoOutputFormat.MP4,
        reference_paths=reference_paths or [],
    )


def test_ark_create_poll_download_and_usage(workspace_tmp_path: Path) -> None:
    reference = workspace_tmp_path / "reference.png"
    image_bytes = create_png_bytes()
    reference.write_bytes(image_bytes)
    requests: list[httpx.Request] = []
    poll_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"id": "ark-task-1"})
        if request.url.host == "cdn.example.com":
            return httpx.Response(200, content=MOCK_MP4)
        poll_count += 1
        if poll_count == 1:
            return httpx.Response(200, json={"id": "ark-task-1", "status": "queued"})
        return httpx.Response(
            200,
            json={
                "id": "ark-task-1",
                "status": "succeeded",
                "content": {"video_url": "https://cdn.example.com/result.mp4"},
                "usage": {"completion_tokens": 120, "total_tokens": 120},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = VolcengineArkVideoGenerationProvider(
        "ark-test-key",
        "doubao-seedance-2-0-260128",
        client=client,
        sleep=no_sleep,
    )
    result = asyncio.run(
        generate_and_close_client(
            provider,
            make_request(reference_paths=[reference]),
            client,
        )
    )

    payload = json.loads(requests[0].content)
    assert requests[0].url.path == "/api/v3/contents/generations/tasks"
    assert requests[0].headers["authorization"] == "Bearer ark-test-key"
    assert payload["model"] == "doubao-seedance-2-0-mini-260615"
    assert payload["resolution"] == "720p"
    assert payload["ratio"] == "9:16"
    assert payload["duration"] == 5
    assert payload["generate_audio"] is True
    assert payload["content"][0] == {
        "type": "text",
        "text": "A cat walking through neon rain",
    }
    image_item = payload["content"][1]
    assert image_item["role"] == "reference_image"
    prefix, encoded = image_item["image_url"]["url"].split(",", 1)
    assert prefix == "data:image/png;base64"
    assert base64.b64decode(encoded) == image_bytes
    assert "authorization" not in requests[-1].headers
    assert result.provider_task_id == "ark-task-1"
    assert result.content == MOCK_MP4
    assert result.usage is not None
    assert result.usage.output_tokens == 120
    assert result.usage.total_tokens == 120


def test_ark_maps_first_frame_and_smart_duration(workspace_tmp_path: Path) -> None:
    reference = workspace_tmp_path / "first.jpg"
    reference.write_bytes(b"jpeg-content")
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(500))
    )
    provider = VolcengineArkVideoGenerationProvider(
        "key",
        "model",
        client=client,
    )
    payload = provider._build_payload(
        make_request(
            reference_mode=VideoReferenceMode.FIRST_FRAME,
            duration_mode=VideoDurationMode.SMART,
            fixed_duration=None,
            output_sound=False,
            reference_paths=[reference],
        )
    )
    asyncio.run(client.aclose())

    assert payload["content"][1]["role"] == "first_frame"
    assert payload["content"][1]["image_url"]["url"].startswith(
        "data:image/jpeg;base64,"
    )
    assert payload["generate_audio"] is False
    assert "duration" not in payload


@pytest.mark.parametrize(
    ("status_code", "provider_code", "expected_code"),
    [
        (401, "Unauthorized", "ARK_AUTH_ERROR"),
        (429, "RateLimitExceeded", "ARK_RATE_LIMITED"),
        (429, "QuotaExceeded", "ARK_QUOTA_EXCEEDED"),
        (400, "InputTextSensitiveContentDetected", "ARK_CONTENT_SAFETY_BLOCKED"),
        (400, "InvalidEndpointOrModel.NotFound", "ARK_MODEL_NOT_FOUND"),
        (500, "InternalServiceError", "ARK_SERVICE_ERROR"),
    ],
)
def test_ark_http_errors_are_normalized(
    status_code: int,
    provider_code: str,
    expected_code: str,
) -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                status_code,
                headers={"x-tt-logid": "log-id-1"},
                json={"error": {"code": provider_code, "message": "vendor detail"}},
            )
        )
    )
    provider = VolcengineArkVideoGenerationProvider("key", "model", client=client)
    with pytest.raises(AppError) as raised:
        asyncio.run(generate_and_close_client(provider, make_request(), client))

    assert raised.value.code == expected_code
    assert "vendor detail" not in raised.value.message
    assert "log-id-1" in raised.value.message


def test_ark_failed_task_maps_content_safety_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "ark-task-failed"})
        return httpx.Response(
            200,
            json={
                "id": "ark-task-failed",
                "status": "failed",
                "error": {"code": "OutputVideoSensitiveContentDetected"},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = VolcengineArkVideoGenerationProvider("key", "model", client=client)
    with pytest.raises(AppError) as raised:
        asyncio.run(generate_and_close_client(provider, make_request(), client))

    assert raised.value.code == "ARK_CONTENT_SAFETY_BLOCKED"


def test_ark_polling_timeout_is_bounded() -> None:
    poll_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        if request.method == "POST":
            return httpx.Response(200, json={"id": "ark-task-running"})
        poll_count += 1
        return httpx.Response(200, json={"status": "running"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = VolcengineArkVideoGenerationProvider(
        "key",
        "model",
        poll_interval=1,
        generation_timeout=2,
        client=client,
        sleep=no_sleep,
    )
    with pytest.raises(AppError) as raised:
        asyncio.run(generate_and_close_client(provider, make_request(), client))

    assert raised.value.code == "ARK_GENERATION_TIMEOUT"
    assert poll_count == 2


def test_ark_rejects_invalid_download() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "ark-task-1"})
        if request.url.host == "cdn.example.com":
            return httpx.Response(200, content=b"<html>expired</html>")
        return httpx.Response(
            200,
            json={
                "status": "succeeded",
                "content": {"video_url": "https://cdn.example.com/result.mp4"},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = VolcengineArkVideoGenerationProvider("key", "model", client=client)
    with pytest.raises(AppError) as raised:
        asyncio.run(generate_and_close_client(provider, make_request(), client))

    assert raised.value.code == "ARK_INVALID_VIDEO_DATA"


def test_ark_poll_connect_error_retries_existing_task_then_succeeds(
    caplog: pytest.LogCaptureFixture,
) -> None:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []
    poll_count = 0

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"id": "ark-existing-task"})
        if request.url.host == "cdn.example.com":
            return httpx.Response(200, content=MOCK_MP4)
        poll_count += 1
        if poll_count == 1:
            raise httpx.ConnectError(
                "temporary poll failure at "
                "https://cdn.example.com/video.mp4?Signature=top-secret",
                request=request,
            )
        if poll_count == 2:
            return httpx.Response(
                200,
                json={"id": "ark-existing-task", "status": "running"},
            )
        return httpx.Response(
            200,
            json={
                "id": "ark-existing-task",
                "status": "succeeded",
                "content": {"video_url": "https://cdn.example.com/result.mp4"},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = VolcengineArkVideoGenerationProvider(
        "key",
        "model",
        poll_interval=5,
        poll_network_retries=3,
        poll_retry_base_delay=2,
        client=client,
        sleep=record_sleep,
    )
    with caplog.at_level(
        logging.WARNING,
        logger="app.providers.video.volcengine_ark_provider",
    ):
        result = asyncio.run(
            generate_and_close_client(provider, make_request(), client)
        )

    create_requests = [request for request in requests if request.method == "POST"]
    poll_requests = [
        request
        for request in requests
        if request.method == "GET" and request.url.host != "cdn.example.com"
    ]
    assert len(create_requests) == 1
    assert len(poll_requests) == 3
    assert {
        request.url.path for request in poll_requests
    } == {"/api/v3/contents/generations/tasks/ark-existing-task"}
    assert result.provider_task_id == "ark-existing-task"
    assert result.content == MOCK_MP4
    assert sleeps == [2, 5]
    assert "local_task_id=1" in caplog.text
    assert "provider_task_id=ark-existing-task" in caplog.text
    assert "stage=poll" in caplog.text
    assert "aspect_ratio=9:16" in caplog.text
    assert "retry_number=1" in caplog.text
    assert "exception_type=ConnectError" in caplog.text
    assert "top-secret" not in caplog.text


def test_ark_poll_connect_error_exhausts_retries_without_recreating() -> None:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"id": "ark-existing-task"})
        raise httpx.ConnectError("persistent poll failure", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = VolcengineArkVideoGenerationProvider(
        "key",
        "model",
        poll_network_retries=3,
        poll_retry_base_delay=2,
        client=client,
        sleep=record_sleep,
    )
    with pytest.raises(AppError) as raised:
        asyncio.run(generate_and_close_client(provider, make_request(), client))

    assert raised.value.code == "ARK_NETWORK_ERROR"
    assert provider.last_provider_task_id == "ark-existing-task"
    assert len([request for request in requests if request.method == "POST"]) == 1
    assert len([request for request in requests if request.method == "GET"]) == 4
    assert sleeps == [2, 4, 8]


def test_ark_create_connect_error_is_not_retried() -> None:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ConnectError("create failed", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = VolcengineArkVideoGenerationProvider(
        "key",
        "model",
        poll_network_retries=3,
        client=client,
        sleep=record_sleep,
    )
    with pytest.raises(AppError) as raised:
        asyncio.run(generate_and_close_client(provider, make_request(), client))

    assert raised.value.code == "ARK_NETWORK_ERROR"
    assert provider.last_provider_task_id is None
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert sleeps == []


def test_ark_exception_repr_redacts_signed_url() -> None:
    signed_url = (
        "https://cdn.example.com/video.mp4?"
        "X-Amz-Credential=test&X-Amz-Signature=top-secret"
    )

    value = VolcengineArkVideoGenerationProvider._safe_exception_repr(
        RuntimeError(
            f"download failed: {signed_url}; Authorization: Bearer secret-token"
        )
    )

    assert "https://" not in value
    assert "top-secret" not in value
    assert "secret-token" not in value
    assert "<redacted-url>" in value
    assert "Bearer <redacted>" in value
