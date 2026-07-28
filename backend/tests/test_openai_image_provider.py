import asyncio
import base64
import json

import httpx
import pytest

from app.core.exceptions import AppError
from app.models.image import ImageAspectRatio, ImageOutputFormat
from app.providers.image.base import ImageGenerationRequest
from app.providers.image.openai_provider import OpenAIImageGenerationProvider
from tests.image_helpers import create_png_bytes


def test_openai_generation_request_and_usage() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            headers={"x-request-id": "req-generation"},
            json={
                "data": [
                    {"b64_json": base64.b64encode(create_png_bytes()).decode()}
                    for _ in range(2)
                ],
                "usage": {"input_tokens": 5, "output_tokens": 7, "total_tokens": 12},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAIImageGenerationProvider(
        "test-key",
        "gpt-image-2",
        organization="org-test",
        project="proj-test",
        client=client,
    )
    request = ImageGenerationRequest(
        task_id=1,
        prompt="portrait",
        aspect_ratio=ImageAspectRatio.PORTRAIT_9_16,
        image_count=2,
        output_format=ImageOutputFormat.PNG,
        reference_paths=[],
    )
    result = asyncio.run(provider.generate(request))
    asyncio.run(client.aclose())

    body = json.loads(captured[0].content)
    assert captured[0].url.path == "/v1/images/generations"
    assert captured[0].headers["authorization"] == "Bearer test-key"
    assert body == {
        "model": "gpt-image-2",
        "prompt": "portrait",
        "n": 2,
        "size": "1024x1824",
        "output_format": "png",
    }
    assert captured[0].headers["openai-organization"] == "org-test"
    assert captured[0].headers["openai-project"] == "proj-test"
    assert result.provider_task_id == "req-generation"
    assert result.usage is not None and result.usage.total_tokens == 12


def test_openai_edit_request_uses_multipart_images(workspace_tmp_path) -> None:
    reference = workspace_tmp_path / "reference.png"
    reference.write_bytes(create_png_bytes())
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"data": [{"b64_json": base64.b64encode(create_png_bytes()).decode()}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAIImageGenerationProvider("test-key", "gpt-image-2", client=client)
    request = ImageGenerationRequest(
        task_id=2,
        prompt="edit",
        aspect_ratio=ImageAspectRatio.SQUARE_1_1,
        image_count=1,
        output_format=ImageOutputFormat.PNG,
        reference_paths=[reference],
    )
    asyncio.run(provider.generate(request))
    asyncio.run(client.aclose())

    content = captured[0].content
    assert captured[0].url.path == "/v1/images/edits"
    assert b'name="image[]"; filename="reference.png"' in content
    assert b'name="size"\r\n\r\n1024x1024' in content
    assert b'name="n"\r\n\r\n1' in content


def test_openai_gpt_image_2_maps_supported_aspect_ratios() -> None:
    provider = OpenAIImageGenerationProvider(
        "test-key",
        "gpt-image-2",
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500))),
    )
    base = {
        "task_id": 1,
        "prompt": "test",
        "image_count": 1,
        "output_format": ImageOutputFormat.PNG,
        "reference_paths": [],
    }
    assert provider._size(
        ImageGenerationRequest(
            **base,
            aspect_ratio=ImageAspectRatio.PORTRAIT_9_16,
        )
    ) == "1024x1824"
    assert provider._size(
        ImageGenerationRequest(
            **base,
            aspect_ratio=ImageAspectRatio.PORTRAIT_3_4,
        )
    ) == "1008x1344"
    assert provider._size(
        ImageGenerationRequest(
            **base,
            aspect_ratio=ImageAspectRatio.SQUARE_1_1,
        )
    ) == "1024x1024"
    asyncio.run(provider.client.aclose())


@pytest.mark.parametrize(
    ("status_code", "error_code", "expected_code"),
    [
        (401, "invalid_api_key", "OPENAI_AUTH_ERROR"),
        (429, "rate_limit_exceeded", "OPENAI_RATE_LIMITED"),
        (429, "insufficient_quota", "OPENAI_QUOTA_EXCEEDED"),
        (400, "moderation_blocked", "OPENAI_MODERATION_BLOCKED"),
        (400, "billing_hard_limit_reached", "OPENAI_BILLING_LIMIT_REACHED"),
        (500, "server_error", "OPENAI_SERVICE_ERROR"),
    ],
)
def test_openai_errors_are_normalized(
    status_code: int,
    error_code: str,
    expected_code: str,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            headers={"x-request-id": "req-error"},
            json={
                "error": {
                    "type": "image_generation_user_error",
                    "code": error_code,
                    "message": "vendor detail",
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAIImageGenerationProvider("test-key", "gpt-image-2", client=client)
    request = ImageGenerationRequest(
        task_id=1,
        prompt="test",
        aspect_ratio=ImageAspectRatio.SQUARE_1_1,
        image_count=1,
        output_format=ImageOutputFormat.PNG,
        reference_paths=[],
    )
    with pytest.raises(AppError) as raised:
        asyncio.run(provider.generate(request))
    asyncio.run(client.aclose())

    assert raised.value.code == expected_code
    assert "req-error" in raised.value.message
    assert "vendor detail" not in raised.value.message


def test_openai_rejects_invalid_base64_response() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"data": [{"b64_json": "%%%"}]})
        )
    )
    provider = OpenAIImageGenerationProvider("test-key", "gpt-image-2", client=client)
    request = ImageGenerationRequest(
        task_id=1,
        prompt="test",
        aspect_ratio=ImageAspectRatio.SQUARE_1_1,
        image_count=1,
        output_format=ImageOutputFormat.PNG,
        reference_paths=[],
    )
    with pytest.raises(AppError) as raised:
        asyncio.run(provider.generate(request))
    asyncio.run(client.aclose())

    assert raised.value.code == "OPENAI_INVALID_IMAGE_DATA"


def test_openai_network_timeout_is_normalized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAIImageGenerationProvider("test-key", "gpt-image-2", client=client)
    request = ImageGenerationRequest(
        task_id=1,
        prompt="test",
        aspect_ratio=ImageAspectRatio.SQUARE_1_1,
        image_count=1,
        output_format=ImageOutputFormat.PNG,
        reference_paths=[],
    )
    with pytest.raises(AppError) as raised:
        asyncio.run(provider.generate(request))
    asyncio.run(client.aclose())

    assert raised.value.code == "OPENAI_TIMEOUT"
