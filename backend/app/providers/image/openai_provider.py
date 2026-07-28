import base64
import binascii
import logging
from collections.abc import Mapping
from typing import Any

import httpx

from app.core.exceptions import AppError
from app.providers.image.base import (
    GeneratedImage,
    ImageGenerationProvider,
    ImageGenerationRequest,
    ImageGenerationResult,
    ImageProviderUsage,
)

logger = logging.getLogger(__name__)


class OpenAIImageGenerationProvider(ImageGenerationProvider):
    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 180.0,
        organization: str = "",
        project: str = "",
        client: httpx.AsyncClient | None = None,
    ):
        if not api_key.strip():
            raise AppError("OPENAI_API_KEY 未配置", "OPENAI_API_KEY_MISSING", 500)
        if not model.strip():
            raise AppError("OPENAI_IMAGE_MODEL 未配置", "OPENAI_MODEL_MISSING", 500)

        self.model = model.strip()
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,
        )
        self.headers = {"Authorization": f"Bearer {api_key.strip()}"}
        if organization.strip():
            self.headers["OpenAI-Organization"] = organization.strip()
        if project.strip():
            self.headers["OpenAI-Project"] = project.strip()

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        try:
            response = (
                await self._edit(request)
                if request.reference_paths
                else await self._create(request)
            )
        except httpx.TimeoutException as exc:
            raise AppError(
                "OpenAI 图片请求超时，请稍后重试",
                "OPENAI_TIMEOUT",
                504,
            ) from exc
        except httpx.RequestError as exc:
            raise AppError(
                "无法连接 OpenAI 图片服务",
                "OPENAI_NETWORK_ERROR",
                502,
            ) from exc

        self._raise_provider_error(response)
        body = self._parse_response_json(response)
        images = self._parse_images(body, request.image_count)
        usage = self._parse_usage(body.get("usage"))
        request_id = response.headers.get("x-request-id")
        return ImageGenerationResult(request_id, images, usage)

    async def _create(self, request: ImageGenerationRequest) -> httpx.Response:
        return await self.client.post(
            f"{self.base_url}/images/generations",
            headers={**self.headers, "Content-Type": "application/json"},
            json={
                "model": self.model,
                "prompt": request.prompt,
                "n": request.image_count,
                "size": self._size(request),
                "output_format": request.output_format.value.lower(),
            },
        )

    async def _edit(self, request: ImageGenerationRequest) -> httpx.Response:
        files: list[tuple[str, tuple[str, bytes, str]]] = []
        for path in request.reference_paths:
            mime_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
            files.append(("image[]", (path.name, path.read_bytes(), mime_type)))
        return await self.client.post(
            f"{self.base_url}/images/edits",
            headers=self.headers,
            data={
                "model": self.model,
                "prompt": request.prompt,
                "n": str(request.image_count),
                "size": self._size(request),
                "output_format": request.output_format.value.lower(),
            },
            files=files,
        )

    def _size(self, request: ImageGenerationRequest) -> str:
        ratio = request.aspect_ratio.value
        if self.model == "gpt-image-2" or self.model.startswith("gpt-image-2-"):
            return {
                "1:1": "1024x1024",
                "3:4": "1008x1344",
                "9:16": "1024x1824",
            }[ratio]
        return "1024x1024" if ratio == "1:1" else "1024x1536"

    @staticmethod
    def _parse_response_json(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise AppError(
                "OpenAI 返回了无法解析的响应",
                "OPENAI_INVALID_RESPONSE",
                502,
            ) from exc
        if not isinstance(body, dict):
            raise AppError(
                "OpenAI 返回的数据结构不正确",
                "OPENAI_INVALID_RESPONSE",
                502,
            )
        return body

    @staticmethod
    def _parse_images(
        body: Mapping[str, Any],
        expected_count: int,
    ) -> list[GeneratedImage]:
        data = body.get("data")
        if not isinstance(data, list):
            raise AppError(
                "OpenAI 响应缺少图片数据",
                "OPENAI_INVALID_RESPONSE",
                502,
            )

        images: list[GeneratedImage] = []
        try:
            for item in data:
                if not isinstance(item, dict) or not isinstance(item.get("b64_json"), str):
                    raise ValueError
                content = base64.b64decode(item["b64_json"], validate=True)
                if not content:
                    raise ValueError
                images.append(GeneratedImage(content, "png"))
        except (ValueError, binascii.Error) as exc:
            raise AppError(
                "OpenAI 返回了无效的图片数据",
                "OPENAI_INVALID_IMAGE_DATA",
                502,
            ) from exc

        if len(images) != expected_count:
            raise AppError(
                f"OpenAI 返回图片数量不正确：期望 {expected_count}，实际 {len(images)}",
                "OPENAI_IMAGE_COUNT_MISMATCH",
                502,
            )
        return images

    @staticmethod
    def _parse_usage(value: Any) -> ImageProviderUsage | None:
        if not isinstance(value, dict):
            return None
        return ImageProviderUsage(
            input_tokens=OpenAIImageGenerationProvider._optional_int(
                value.get("input_tokens")
            ),
            output_tokens=OpenAIImageGenerationProvider._optional_int(
                value.get("output_tokens")
            ),
            total_tokens=OpenAIImageGenerationProvider._optional_int(
                value.get("total_tokens")
            ),
        )

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @staticmethod
    def _raise_provider_error(response: httpx.Response) -> None:
        if response.is_success:
            return

        request_id = response.headers.get("x-request-id")
        error: Mapping[str, Any] = {}
        try:
            body = response.json()
            if isinstance(body, dict) and isinstance(body.get("error"), dict):
                error = body["error"]
        except ValueError:
            pass

        provider_code = str(error.get("code") or "")
        provider_type = str(error.get("type") or "")
        status = response.status_code
        log_values = {
            "status": status,
            "provider_code": provider_code or None,
            "provider_type": provider_type or None,
            "request_id": request_id,
        }
        logger.warning("OpenAI image request failed: %s", log_values)

        suffix = f"（请求 ID：{request_id}）" if request_id else ""
        if provider_code == "moderation_blocked":
            raise AppError(
                f"图片请求未通过 OpenAI 安全检查，请调整提示词或参考图片{suffix}",
                "OPENAI_MODERATION_BLOCKED",
                422,
            )
        if provider_code in {"billing_hard_limit_reached", "billing_not_active"}:
            raise AppError(
                f"OpenAI 账户计费未启用或已达到消费上限{suffix}",
                "OPENAI_BILLING_LIMIT_REACHED",
                503,
            )
        if status in {401, 403}:
            raise AppError(
                f"OpenAI 凭证无效或无权使用当前模型{suffix}",
                "OPENAI_AUTH_ERROR",
                502,
            )
        if status == 429:
            code = (
                "OPENAI_QUOTA_EXCEEDED"
                if provider_code == "insufficient_quota"
                else "OPENAI_RATE_LIMITED"
            )
            message = (
                "OpenAI 账户额度不足"
                if code == "OPENAI_QUOTA_EXCEEDED"
                else "OpenAI 请求频率受限，请稍后重试"
            )
            raise AppError(f"{message}{suffix}", code, 503)
        if status >= 500:
            raise AppError(
                f"OpenAI 图片服务暂时不可用{suffix}",
                "OPENAI_SERVICE_ERROR",
                502,
            )
        if status in {400, 404, 409, 422} or provider_type == "image_generation_user_error":
            raise AppError(
                f"OpenAI 拒绝了图片请求，请检查模型、提示词和参考图片{suffix}",
                "OPENAI_INVALID_REQUEST",
                422,
            )
        raise AppError(
            f"OpenAI 图片请求失败{suffix}",
            "OPENAI_REQUEST_FAILED",
            502,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()
