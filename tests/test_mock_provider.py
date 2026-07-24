from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tk_video_generate.enums import TaskStatus
from tk_video_generate.models import VideoTask
from tk_video_generate.providers.base import ProviderError
from tk_video_generate.providers.mock_provider import MockVideoProvider
from tk_video_generate.services.time import now_iso


def make_task(sample_image: Path, aspect_ratio: str, prompt: str = "normal prompt") -> VideoTask:
    now = now_iso()
    return VideoTask(
        id=f"TASK_{aspect_ratio.replace(':', '_')}_{abs(hash(prompt))}",
        batch_id="BATCH_PROVIDER",
        name="Provider Task",
        image_path=str(sample_image),
        prompt=prompt,
        provider="mock",
        duration_seconds=3,
        aspect_ratio=aspect_ratio,
        status=TaskStatus.RUNNING,
        progress=10,
        provider_task_id=None,
        output_video_path=None,
        request_json_path=None,
        result_json_path=None,
        retry_count=0,
        error_code=None,
        error_message=None,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )


@pytest.mark.parametrize(
    ("aspect_ratio", "expected"),
    [("9:16", (540, 960)), ("1:1", (720, 720)), ("16:9", (960, 540))],
)
def test_mock_provider_outputs_expected_dimensions_and_codec(
    app_config,
    sample_image,
    aspect_ratio,
    expected,
) -> None:
    provider = MockVideoProvider(app_config)
    task = make_task(sample_image, aspect_ratio)

    result = provider.generate(task, app_config.outputs_dir / task.batch_id / task.id)
    stream = result["ffprobe"]["streams"][0]

    assert (stream["width"], stream["height"]) == expected
    assert stream["codec_name"] == "h264"
    assert stream["pix_fmt"] == "yuv420p"


def test_mock_provider_writes_request_result_and_mp4_with_time_fields(
    app_config,
    sample_image,
) -> None:
    provider = MockVideoProvider(app_config)
    task = make_task(sample_image, "9:16")
    output_dir = app_config.outputs_dir / task.batch_id / task.id

    result = provider.generate(task, output_dir)

    request_json = output_dir / "request.json"
    result_json = output_dir / "result.json"
    mp4 = output_dir / "result.mp4"
    parsed_result = json.loads(result_json.read_text(encoding="utf-8"))

    assert request_json.exists()
    assert result_json.exists()
    assert mp4.exists()
    assert result["status"] == TaskStatus.SUCCEEDED.value
    assert parsed_result["status"] == TaskStatus.SUCCEEDED.value
    assert parsed_result["requested_at"]
    assert parsed_result["completed_at"]


@pytest.mark.parametrize(
    ("prompt", "code"),
    [
        ("[mock-fail] fail", "MOCK_FORCED_FAILURE"),
        ("[mock-timeout] timeout", "MOCK_TIMEOUT"),
    ],
)
def test_mock_provider_forced_failures_are_deterministic_and_fast(
    app_config,
    sample_image,
    prompt,
    code,
) -> None:
    provider = MockVideoProvider(app_config)
    task = make_task(sample_image, "16:9", prompt=prompt)

    started = time.monotonic()
    with pytest.raises(ProviderError) as exc_info:
        provider.generate(task, app_config.outputs_dir / task.batch_id / task.id)

    assert exc_info.value.code == code
    assert time.monotonic() - started < 1.0
