from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from tk_video_generate.config import AppConfig
from tk_video_generate.models import VideoTask
from tk_video_generate.providers.base import (
    ProviderError,
    ProviderPollResult,
    ProviderSubmission,
    VideoProvider,
)

TRANSIENT_HTTP_STATUS = {429, 500, 502, 503}


class BytePlusSeedanceProvider(VideoProvider):
    """BytePlus ModelArk Seedance provider.

    Contract recorded from official BytePlus ModelArk API documentation accessed
    2026-07-24. Real submissions use a task-level HTTPS first-frame URL.
    """

    name = "byteplus_seedance"
    channel = "BytePlus ModelArk"
    documentation_url = "https://docs.byteplus.com/en/docs/ModelArk/1520757"
    api_version = "ModelArk API v3"

    def __init__(self, config: AppConfig, client: httpx.Client | None = None) -> None:
        self.config = config
        self.client = client or httpx.Client(
            base_url=config.seedance_base_url.rstrip("/"),
            timeout=httpx.Timeout(config.seedance_request_timeout_seconds),
        )

    def validate(self, task: VideoTask) -> None:
        try:
            self.config.validate_seedance_config()
        except ValueError as exc:
            raise ProviderError("PROVIDER_CONFIG_MISSING", str(exc)) from exc
        if not task.image_url:
            raise ProviderError(
                "PROVIDER_VALIDATION_ERROR",
                "Seedance task image_url is required.",
            )
        parsed = urlparse(task.image_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ProviderError("PROVIDER_VALIDATION_ERROR", "Seedance image_url must be HTTPS.")
        if task.duration_seconds not in {3, 5, 10}:
            raise ProviderError("PROVIDER_VALIDATION_ERROR", "Unsupported duration.")
        if task.aspect_ratio not in {"9:16", "1:1", "16:9"}:
            raise ProviderError("PROVIDER_VALIDATION_ERROR", "Unsupported aspect ratio.")

    def estimate_cost(self, task: VideoTask) -> float | None:
        return None

    def submit(self, task: VideoTask, output_dir: Path) -> ProviderSubmission:
        self.validate(task)
        payload = self.request_payload(task)
        self._write_json(output_dir / "request.json", self.redacted_payload(payload))
        response = self._request("POST", "/contents/generations/tasks", json=payload)
        raw = self._json_response(response)
        provider_task_id = self._extract_task_id(raw)
        if not provider_task_id:
            raise ProviderError(
                "PROVIDER_SUBMIT_FAILED",
                "Provider response did not include task id.",
            )
        self._write_json(output_dir / "provider_submit_response.json", self._redact(raw))
        return ProviderSubmission(provider_task_id=provider_task_id, raw_response=self._redact(raw))

    def poll(self, provider_task_id: str) -> ProviderPollResult:
        response = self._request("GET", f"/contents/generations/tasks/{provider_task_id}")
        raw = self._json_response(response)
        redacted = self._redact(raw)
        provider_status = self._extract_status(raw)
        mapped = self._map_status(provider_status)
        result_url = self._extract_result_url(raw)
        error_code, error_message = self._extract_error(raw)

        if mapped == "unknown":
            return ProviderPollResult(
                status="failed",
                progress=None,
                result_url=None,
                error_code="PROVIDER_UNKNOWN_STATUS",
                error_message=f"Unknown provider status: {provider_status}",
                raw_response=redacted,
            )
        if mapped == "succeeded" and not result_url:
            return ProviderPollResult(
                status="failed",
                progress=100,
                result_url=None,
                error_code="RESULT_URL_MISSING",
                error_message="Provider reported success without a result URL.",
                raw_response=redacted,
            )
        return ProviderPollResult(
            status=mapped,
            progress=self._extract_progress(raw),
            result_url=result_url,
            error_code=error_code,
            error_message=error_message,
            raw_response=redacted,
        )

    def download(self, result_url: str, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.client.stream("GET", result_url) as response:
                response.raise_for_status()
                with output_path.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        if chunk:
                            handle.write(chunk)
        except httpx.HTTPError as exc:
            raise ProviderError(
                "RESULT_DOWNLOAD_FAILED",
                "Provider result download failed.",
            ) from exc
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise ProviderError("RESULT_DOWNLOAD_FAILED", "Downloaded result is empty.")
        return output_path

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.config.seedance_api_key}"
        try:
            response = self.client.request(method, path, headers=headers, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 401 or status == 403:
                code = "PROVIDER_AUTH_ERROR"
            elif status == 429:
                code = "PROVIDER_RATE_LIMITED"
            elif status in TRANSIENT_HTTP_STATUS:
                code = "PROVIDER_TEMPORARY_ERROR"
            else:
                code = "PROVIDER_SUBMIT_FAILED"
            raise ProviderError(
                code,
                f"Provider HTTP request failed with status {status}.",
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("PROVIDER_SUBMIT_FAILED", "Provider HTTP request failed.") from exc

    def request_payload(self, task: VideoTask) -> dict[str, Any]:
        self.validate(task)
        return {
            "model": self.config.seedance_model,
            "content": [
                {"type": "text", "text": task.prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": task.image_url},
                    "role": "first_frame",
                },
            ],
            "duration": task.duration_seconds,
            "ratio": task.aspect_ratio,
        }

    def build_redacted_request(self, task: VideoTask) -> dict[str, Any]:
        """Return the exact submit request shape with sensitive fields redacted."""
        return {
            "method": "POST",
            "url": f"{self.config.seedance_base_url.rstrip('/')}/contents/generations/tasks",
            "headers": {
                "Content-Type": "application/json",
                "Authorization": "Bearer [REDACTED]",
            },
            "json": self.redacted_payload(self.request_payload(task)),
        }

    def _json_response(self, response: httpx.Response) -> dict[str, Any]:
        try:
            parsed = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderError(
                "PROVIDER_SUBMIT_FAILED",
                "Provider response was not JSON.",
            ) from exc
        if not isinstance(parsed, dict):
            raise ProviderError(
                "PROVIDER_SUBMIT_FAILED",
                "Provider response JSON was not an object.",
            )
        return parsed

    def _extract_task_id(self, raw: dict[str, Any]) -> str | None:
        value = raw.get("id")
        return str(value) if value else None

    def _extract_status(self, raw: dict[str, Any]) -> str:
        value = raw.get("status")
        return str(value or "unknown").lower()

    def _map_status(self, provider_status: str) -> str:
        if provider_status in {"queued", "pending", "created", "submitted"}:
            return "queued"
        if provider_status in {"running", "processing", "in_progress"}:
            return "running"
        if provider_status in {"succeeded", "success", "completed"}:
            return "succeeded"
        if provider_status in {"failed", "error", "expired"}:
            return "failed"
        if provider_status in {"cancelled", "canceled"}:
            return "cancelled"
        return "unknown"

    def _extract_result_url(self, raw: dict[str, Any]) -> str | None:
        content = raw.get("content")
        if isinstance(content, dict):
            value = content.get("video_url")
            return str(value) if value else None
        return None

    def _extract_progress(self, raw: dict[str, Any]) -> int | None:
        value = raw.get("progress")
        return int(value) if isinstance(value, int | float) else None

    def _extract_error(self, raw: dict[str, Any]) -> tuple[str | None, str | None]:
        error = raw.get("error")
        if isinstance(error, dict):
            return str(error.get("code") or "PROVIDER_TASK_FAILED"), str(
                error.get("message") or "Provider task failed."
            )
        if error:
            return "PROVIDER_TASK_FAILED", "Provider task failed."
        return None, None

    def redacted_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        redacted = self._redact(payload)
        for item in redacted.get("content", []):
            if isinstance(item, dict) and item.get("type") == "image_url":
                url = item.get("image_url", {}).get("url")
                host = urlparse(url).netloc if isinstance(url, str) else ""
                item["image_url"] = {"url": f"[REDACTED_URL_HOST:{host or 'unknown'}]"}
        return redacted

    def _redact(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: ("[REDACTED]" if self._is_sensitive_key(key) else self._redact(item))
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if (
            isinstance(value, str)
            and self.config.seedance_api_key
            and self.config.seedance_api_key in value
        ):
            return value.replace(self.config.seedance_api_key, "[REDACTED]")
        return value

    def _is_sensitive_key(self, key: str) -> bool:
        lowered = key.lower()
        return any(marker in lowered for marker in ("key", "token", "secret", "authorization"))

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
