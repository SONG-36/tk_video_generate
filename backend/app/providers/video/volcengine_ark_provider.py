import asyncio
import base64
import logging
import math
import re
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.exceptions import AppError
from app.models.video import VideoDurationMode, VideoReferenceMode
from app.providers.video.base import (
    VideoGenerationProvider,
    VideoGenerationRequest,
    VideoGenerationResult,
    VideoProviderUsage,
)
from app.services.video_prompt import (
    VideoPromptReferenceError,
    normalize_video_prompt,
)

logger = logging.getLogger(__name__)

_CONTENT_SAFETY_CODES = {
    "InputTextSensitiveContentDetected",
    "InputImageSensitiveContentDetected",
    "OutputVideoSensitiveContentDetected",
}


class VolcengineArkVideoGenerationProvider(VideoGenerationProvider):
    name = "volcengine_ark"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
        request_timeout: float = 60.0,
        poll_interval: float = 5.0,
        poll_network_retries: int = 3,
        poll_retry_base_delay: float = 2.0,
        generation_timeout: float = 900.0,
        max_download_bytes: int = 200 * 1024 * 1024,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        if not api_key.strip():
            raise AppError("ARK_API_KEY 未配置", "ARK_API_KEY_MISSING", 500)
        if not model.strip():
            raise AppError("ARK_VIDEO_MODEL 未配置", "ARK_VIDEO_MODEL_MISSING", 500)
        if poll_interval <= 0 or generation_timeout <= 0:
            raise ValueError("轮询间隔和生成超时必须大于 0")
        if poll_network_retries < 0:
            raise ValueError("轮询网络重试次数不能小于 0")
        if poll_retry_base_delay <= 0:
            raise ValueError("轮询网络重试基础等待时间必须大于 0")
        if max_download_bytes <= 0:
            raise ValueError("最大下载字节数必须大于 0")

        self.model = model.strip()
        self.base_url = base_url.rstrip("/")
        self.poll_interval = poll_interval
        self.poll_network_retries = poll_network_retries
        self.poll_retry_base_delay = poll_retry_base_delay
        self.generation_timeout = generation_timeout
        self.max_download_bytes = max_download_bytes
        self._sleep = sleep
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(request_timeout),
            follow_redirects=True,
        )
        self.headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json",
        }
        self.last_provider_task_id: str | None = None
        self.last_aspect_ratio: str | None = None

    async def generate(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        stage = "create"
        self.last_provider_task_id = None
        self.last_aspect_ratio = request.aspect_ratio.value
        try:
            task_id = await self._create_task(request)
            self.last_provider_task_id = task_id
            stage = "poll"
            task = await self._wait_for_task(task_id, request)
            stage = "download"
            content = await self._download_video(
                self._video_url(task),
                request=request,
                provider_task_id=task_id,
            )
        except httpx.TimeoutException as exc:
            self._log_request_exception(
                request,
                stage=stage,
                provider_task_id=self.last_provider_task_id,
                exc=exc,
            )
            raise AppError(
                "火山方舟视频请求超时，请稍后重试",
                "ARK_REQUEST_TIMEOUT",
                504,
            ) from exc
        except httpx.RequestError as exc:
            self._log_request_exception(
                request,
                stage=stage,
                provider_task_id=self.last_provider_task_id,
                exc=exc,
            )
            raise AppError(
                "无法连接火山方舟视频服务",
                "ARK_NETWORK_ERROR",
                502,
            ) from exc

        return VideoGenerationResult(
            provider_task_id=task_id,
            content=content,
            extension="mp4",
            usage=self._parse_usage(task.get("usage")),
        )

    async def _create_task(self, request: VideoGenerationRequest) -> str:
        response = await self.client.post(
            f"{self.base_url}/contents/generations/tasks",
            headers=self.headers,
            json=self._build_payload(request),
        )
        self._log_http_response(
            response,
            request=request,
            stage="create",
            provider_task_id=None,
        )
        self._raise_http_error(
            response,
            request=request,
            stage="create",
            provider_task_id=None,
        )
        body = self._parse_json(response)
        task_id = body.get("id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise AppError(
                "火山方舟响应缺少视频任务 ID",
                "ARK_INVALID_RESPONSE",
                502,
            )
        logger.info(
            "Created Volcengine Ark video task local_task_id=%s "
            "provider_task_id=%s stage=create aspect_ratio=%s model=%s",
            request.task_id,
            task_id,
            request.aspect_ratio.value,
            request.model,
        )
        return task_id

    async def _wait_for_task(
        self,
        task_id: str,
        request: VideoGenerationRequest,
    ) -> dict[str, Any]:
        attempts = max(1, math.ceil(self.generation_timeout / self.poll_interval))
        previous_status: str | None = None
        for attempt in range(attempts):
            response = await self._get_poll_response(
                task_id,
                request=request,
                poll_attempt=attempt + 1,
            )
            body = self._parse_json(response)
            status = body.get("status")
            if not isinstance(status, str):
                raise AppError(
                    "火山方舟任务响应缺少状态",
                    "ARK_INVALID_RESPONSE",
                    502,
                )
            status = status.lower()
            if status != previous_status:
                logger.info(
                    "Volcengine Ark video task status local_task_id=%s "
                    "provider_task_id=%s stage=poll aspect_ratio=%s "
                    "poll_attempt=%s status=%s",
                    request.task_id,
                    task_id,
                    request.aspect_ratio.value,
                    attempt + 1,
                    status,
                )
                previous_status = status
            if status == "succeeded":
                return body
            if status == "cancelled":
                raise AppError("火山方舟视频任务已取消", "ARK_TASK_CANCELLED", 502)
            if status == "failed":
                self._raise_task_error(body)
            if status not in {"queued", "running"}:
                raise AppError(
                    "火山方舟返回了未知任务状态",
                    "ARK_INVALID_RESPONSE",
                    502,
                )
            if attempt + 1 < attempts:
                await self._sleep(self.poll_interval)
        raise AppError(
            "火山方舟视频生成超时",
            "ARK_GENERATION_TIMEOUT",
            504,
        )

    async def _get_poll_response(
        self,
        provider_task_id: str,
        request: VideoGenerationRequest,
        poll_attempt: int,
    ) -> httpx.Response:
        for retry_index in range(self.poll_network_retries + 1):
            try:
                response = await self.client.get(
                    f"{self.base_url}/contents/generations/tasks/{provider_task_id}",
                    headers=self.headers,
                )
                self._log_http_response(
                    response,
                    request=request,
                    stage="poll",
                    provider_task_id=provider_task_id,
                )
                self._raise_http_error(
                    response,
                    request=request,
                    stage="poll",
                    provider_task_id=provider_task_id,
                )
                return response
            except httpx.TransportError as exc:
                if retry_index >= self.poll_network_retries:
                    logger.error(
                        "Volcengine Ark poll network retries exhausted "
                        "local_task_id=%s provider_task_id=%s stage=poll "
                        "aspect_ratio=%s poll_attempt=%s retry_count=%s "
                        "exception_type=%s exception_repr=%s",
                        request.task_id,
                        provider_task_id,
                        request.aspect_ratio.value,
                        poll_attempt,
                        retry_index,
                        type(exc).__name__,
                        self._safe_exception_repr(exc),
                    )
                    raise
                retry_number = retry_index + 1
                delay = self.poll_retry_base_delay * (2**retry_index)
                logger.warning(
                    "Volcengine Ark poll network error; retrying existing task "
                    "local_task_id=%s provider_task_id=%s stage=poll "
                    "aspect_ratio=%s poll_attempt=%s retry_number=%s "
                    "max_retries=%s retry_delay_seconds=%s exception_type=%s "
                    "exception_repr=%s",
                    request.task_id,
                    provider_task_id,
                    request.aspect_ratio.value,
                    poll_attempt,
                    retry_number,
                    self.poll_network_retries,
                    delay,
                    type(exc).__name__,
                    self._safe_exception_repr(exc),
                )
                await self._sleep(delay)

        raise RuntimeError("unreachable poll retry state")

    def _build_payload(self, request: VideoGenerationRequest) -> dict[str, Any]:
        try:
            # 正常任务已由服务层标准化；这里保留幂等校验，防止其他调用方绕过业务入口。
            prompt = normalize_video_prompt(request.prompt, len(request.reference_paths))
        except VideoPromptReferenceError as exc:
            raise AppError(str(exc), "INVALID_VIDEO_IMAGE_REFERENCE", 422) from exc

        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        role = (
            "first_frame"
            if request.reference_mode == VideoReferenceMode.FIRST_FRAME
            else "reference_image"
        )
        for path in request.reference_paths:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": self._image_data_url(path)},
                    "role": role,
                }
            )

        payload: dict[str, Any] = {
            "model": request.model,
            "content": content,
            "resolution": request.resolution.value.lower(),
            "ratio": request.aspect_ratio.value,
            "generate_audio": request.output_sound,
        }
        if request.duration_mode == VideoDurationMode.FIXED:
            if request.fixed_duration is None:
                raise AppError(
                    "固定时长模式缺少时长参数",
                    "ARK_INVALID_VIDEO_PARAMETERS",
                    422,
                )
            payload["duration"] = request.fixed_duration
        return payload

    async def _download_video(
        self,
        video_url: str,
        request: VideoGenerationRequest,
        provider_task_id: str,
    ) -> bytes:
        parsed = urlparse(video_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise AppError(
                "火山方舟返回了不安全的视频地址",
                "ARK_INVALID_VIDEO_URL",
                502,
            )
        content = bytearray()
        async with self.client.stream("GET", video_url) as response:
            self._log_http_response(
                response,
                request=request,
                stage="download",
                provider_task_id=provider_task_id,
            )
            self._raise_download_error(
                response,
                request=request,
                provider_task_id=provider_task_id,
            )
            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > self.max_download_bytes:
                        raise AppError(
                            "火山方舟生成的视频超过本地下载限制",
                            "ARK_VIDEO_TOO_LARGE",
                            502,
                        )
                except ValueError:
                    pass
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > self.max_download_bytes:
                    raise AppError(
                        "火山方舟生成的视频超过本地下载限制",
                        "ARK_VIDEO_TOO_LARGE",
                        502,
                    )
        if len(content) < 12 or content[4:8] != b"ftyp":
            raise AppError(
                "火山方舟返回的文件不是有效的 MP4 视频",
                "ARK_INVALID_VIDEO_DATA",
                502,
            )
        return bytes(content)

    @staticmethod
    def _image_data_url(path: Path) -> str:
        mime_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
        }.get(path.suffix.lower())
        if mime_type is None:
            raise AppError(
                "火山方舟参考图片格式无效",
                "ARK_INVALID_REFERENCE_IMAGE",
                422,
            )
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise AppError(
                "无法读取火山方舟参考图片",
                "ARK_REFERENCE_IMAGE_READ_ERROR",
                500,
            ) from exc
        if not content:
            raise AppError(
                "火山方舟参考图片为空",
                "ARK_INVALID_REFERENCE_IMAGE",
                422,
            )
        encoded = base64.b64encode(content).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    @staticmethod
    def _video_url(body: Mapping[str, Any]) -> str:
        content = body.get("content")
        if not isinstance(content, dict):
            raise AppError(
                "火山方舟成功响应缺少视频结果",
                "ARK_INVALID_RESPONSE",
                502,
            )
        video_url = content.get("video_url")
        if not isinstance(video_url, str) or not video_url:
            raise AppError(
                "火山方舟成功响应缺少视频地址",
                "ARK_INVALID_RESPONSE",
                502,
            )
        return video_url

    @staticmethod
    def _parse_usage(value: Any) -> VideoProviderUsage | None:
        if not isinstance(value, dict):
            return None
        input_tokens = VolcengineArkVideoGenerationProvider._optional_int(
            value.get("prompt_tokens")
        )
        output_tokens = VolcengineArkVideoGenerationProvider._optional_int(
            value.get("completion_tokens")
        )
        total_tokens = VolcengineArkVideoGenerationProvider._optional_int(
            value.get("total_tokens")
        )
        if input_tokens is None and output_tokens is None and total_tokens is None:
            return None
        return VideoProviderUsage(input_tokens, output_tokens, total_tokens)

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @staticmethod
    def _parse_json(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise AppError(
                "火山方舟返回了无法解析的响应",
                "ARK_INVALID_RESPONSE",
                502,
            ) from exc
        if not isinstance(body, dict):
            raise AppError(
                "火山方舟返回的数据结构不正确",
                "ARK_INVALID_RESPONSE",
                502,
            )
        return body

    @staticmethod
    def _raise_task_error(body: Mapping[str, Any]) -> None:
        error = body.get("error")
        provider_code = (
            str(error.get("code") or "") if isinstance(error, dict) else ""
        )
        VolcengineArkVideoGenerationProvider._raise_mapped_error(
            provider_code,
            request_id=None,
            fallback_code="ARK_GENERATION_FAILED",
            fallback_message="火山方舟视频生成失败",
        )

    def _raise_http_error(
        self,
        response: httpx.Response,
        request: VideoGenerationRequest,
        stage: str,
        provider_task_id: str | None,
    ) -> None:
        if response.is_success:
            return
        provider_code = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                error = body.get("error")
                if isinstance(error, dict):
                    provider_code = str(error.get("code") or "")
                elif isinstance(body.get("code"), str):
                    provider_code = body["code"]
        except ValueError:
            pass
        request_id = response.headers.get("x-tt-logid")
        logger.warning(
            "Volcengine Ark video HTTP error local_task_id=%s "
            "provider_task_id=%s stage=%s aspect_ratio=%s status_code=%s "
            "provider_code=%s request_id=%s sanitized_response=%s",
            request.task_id,
            provider_task_id,
            stage,
            request.aspect_ratio.value,
            response.status_code,
            provider_code or None,
            request_id,
            self._sanitized_response(response, stage),
        )
        if response.status_code in {401, 403}:
            raise AppError(
                VolcengineArkVideoGenerationProvider._with_request_id(
                    "火山方舟凭证无效或无权使用当前模型", request_id
                ),
                "ARK_AUTH_ERROR",
                502,
            )
        if response.status_code == 429:
            code = (
                "ARK_QUOTA_EXCEEDED"
                if provider_code == "QuotaExceeded"
                else "ARK_RATE_LIMITED"
            )
            message = (
                "火山方舟账户额度不足"
                if code == "ARK_QUOTA_EXCEEDED"
                else "火山方舟请求频率受限，请稍后重试"
            )
            raise AppError(
                VolcengineArkVideoGenerationProvider._with_request_id(
                    message, request_id
                ),
                code,
                503,
            )
        if response.status_code >= 500:
            raise AppError(
                VolcengineArkVideoGenerationProvider._with_request_id(
                    "火山方舟视频服务暂时不可用", request_id
                ),
                "ARK_SERVICE_ERROR",
                502,
            )
        VolcengineArkVideoGenerationProvider._raise_mapped_error(
            provider_code,
            request_id,
            fallback_code="ARK_INVALID_REQUEST",
            fallback_message="火山方舟拒绝了视频请求，请检查模型和生成参数",
        )

    def _raise_download_error(
        self,
        response: httpx.Response,
        request: VideoGenerationRequest,
        provider_task_id: str,
    ) -> None:
        if response.is_success:
            return
        logger.warning(
            "Volcengine Ark video HTTP error local_task_id=%s "
            "provider_task_id=%s stage=download aspect_ratio=%s "
            "status_code=%s sanitized_response=%s",
            request.task_id,
            provider_task_id,
            request.aspect_ratio.value,
            response.status_code,
            self._sanitized_response(response, "download"),
        )
        raise AppError(
            "无法下载火山方舟生成的视频",
            "ARK_VIDEO_DOWNLOAD_FAILED",
            502,
        )

    def _log_http_response(
        self,
        response: httpx.Response,
        request: VideoGenerationRequest,
        stage: str,
        provider_task_id: str | None,
    ) -> None:
        if not response.is_success:
            return
        logger.info(
            "Volcengine Ark video HTTP response local_task_id=%s "
            "provider_task_id=%s stage=%s aspect_ratio=%s status_code=%s "
            "sanitized_response=%s",
            request.task_id,
            provider_task_id,
            stage,
            request.aspect_ratio.value,
            response.status_code,
            self._sanitized_response(response, stage),
        )

    @staticmethod
    def _sanitized_response(response: httpx.Response, stage: str) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "content_type": response.headers.get("content-type"),
            "content_length": response.headers.get("content-length"),
        }
        if stage == "download":
            return summary
        try:
            body = response.json()
        except ValueError:
            summary["body"] = "<non-json omitted>"
            return summary
        if not isinstance(body, dict):
            summary["body_type"] = type(body).__name__
            return summary
        for key in ("id", "status", "model"):
            value = body.get(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                summary[key] = value
        error = body.get("error")
        if isinstance(error, dict):
            summary["error"] = {
                key: error.get(key)
                for key in ("code", "type")
                if isinstance(error.get(key), (str, int))
            }
        return summary

    @staticmethod
    def _safe_exception_repr(exc: Exception) -> str:
        value = repr(exc)
        value = re.sub(r"https?://[^\s'\"\)]+", "<redacted-url>", value)
        value = re.sub(
            r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+",
            "Bearer <redacted>",
            value,
        )
        return value[:500]

    def _log_request_exception(
        self,
        request: VideoGenerationRequest,
        stage: str,
        provider_task_id: str | None,
        exc: Exception,
    ) -> None:
        logger.error(
            "Volcengine Ark video request exception local_task_id=%s "
            "provider_task_id=%s stage=%s aspect_ratio=%s model=%s "
            "exception_type=%s exception_repr=%s",
            request.task_id,
            provider_task_id,
            stage,
            request.aspect_ratio.value,
            request.model,
            type(exc).__name__,
            self._safe_exception_repr(exc),
        )

    @staticmethod
    def _raise_mapped_error(
        provider_code: str,
        request_id: str | None,
        fallback_code: str,
        fallback_message: str,
    ) -> None:
        if provider_code in _CONTENT_SAFETY_CODES:
            raise AppError(
                VolcengineArkVideoGenerationProvider._with_request_id(
                    "视频请求未通过火山方舟内容安全检查，请调整提示词或参考图片",
                    request_id,
                ),
                "ARK_CONTENT_SAFETY_BLOCKED",
                422,
            )
        if provider_code in {
            "InvalidEndpointOrModel.NotFound",
            "InvalidModel",
            "ModelNotFound",
        }:
            raise AppError(
                VolcengineArkVideoGenerationProvider._with_request_id(
                    "火山方舟视频模型不存在或尚未开通", request_id
                ),
                "ARK_MODEL_NOT_FOUND",
                422,
            )
        raise AppError(
            VolcengineArkVideoGenerationProvider._with_request_id(
                fallback_message, request_id
            ),
            fallback_code,
            502 if fallback_code == "ARK_GENERATION_FAILED" else 422,
        )

    @staticmethod
    def _with_request_id(message: str, request_id: str | None) -> str:
        return f"{message}（请求 ID：{request_id}）" if request_id else message

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()
