import pytest
from pydantic import ValidationError

from app.schemas.video import VideoBatchCreate
from app.services.video_prompt import (
    VideoPromptReferenceError,
    normalize_video_prompt,
)


def test_normalizes_valid_mentions_without_changing_other_at_characters() -> None:
    prompt = "联系 user@example.com 或 user@图片1.com，单独的 @ 保留；让@图片1拿起@图片5"

    assert normalize_video_prompt(prompt, 5) == (
        "联系 user@example.com 或 user@图片1.com，单独的 @ 保留；让图片1拿起图片5"
    )


@pytest.mark.parametrize("reference", ["@图片0", "@图片-1", "@图片1.5"])
def test_rejects_invalid_image_reference_numbers(reference: str) -> None:
    with pytest.raises(VideoPromptReferenceError, match="格式不合法"):
        normalize_video_prompt(f"错误引用：{reference}", 5)


def test_rejects_reference_above_current_image_count() -> None:
    with pytest.raises(VideoPromptReferenceError, match="@图片6"):
        normalize_video_prompt("让@图片6进入镜头", 5)


@pytest.mark.parametrize(
    "reference",
    ["@图片01", "@图片已删除", "@图片一", "@图片"],
)
def test_rejects_other_malformed_structured_references(reference: str) -> None:
    with pytest.raises(VideoPromptReferenceError, match="格式不合法"):
        normalize_video_prompt(reference, 2)


@pytest.mark.parametrize(
    "prompt",
    [
        "图片1",
        "图片2",
        "普通图片9",
        "user@example.com",
        "user@图片1.com",
        "@",
        "@abc",
        "@人物",
    ],
)
def test_keeps_compatible_non_structured_text(prompt: str) -> None:
    assert normalize_video_prompt(prompt, 2) == prompt


def test_normalizes_repeated_out_of_order_mentions_and_punctuation() -> None:
    assert normalize_video_prompt("@图片2，先看@图片1；again @图片1.", 2) == (
        "图片2，先看图片1；again 图片1."
    )


@pytest.mark.parametrize("reference", ["@图片3", "@图片999"])
def test_rejects_any_reference_above_two_images(reference: str) -> None:
    with pytest.raises(VideoPromptReferenceError, match="不存在"):
        normalize_video_prompt(reference, 2)


def test_video_schema_counts_unicode_characters_at_10000_boundary() -> None:
    base = {
        "reference_mode": "REFERENCE",
        "resolution": "720P",
        "aspect_ratio": "9:16",
        "duration_mode": "SMART",
        "reference_images": [],
    }
    accepted = VideoBatchCreate.model_validate(
        {"tasks": [{**base, "prompt": "😀" * 10000}]}
    )
    assert len(accepted.tasks[0].prompt) == 10000
    with pytest.raises(ValidationError):
        VideoBatchCreate.model_validate(
            {"tasks": [{**base, "prompt": "😀" * 10001}]}
        )
