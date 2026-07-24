from __future__ import annotations

import pytest
from conftest import create_batch, make_upload

from tk_video_generate.services.workbench_service import WorkbenchService


@pytest.mark.parametrize("prompt", ["", "   "])
def test_empty_or_blank_prompt_is_rejected(app_config, image_upload_bytes, prompt) -> None:
    service = WorkbenchService(app_config)

    with pytest.raises(ValueError, match="Prompt cannot be empty"):
        service.create_confirmed_batch(
            batch_id="BATCH_EMPTY_PROMPT",
            batch_name="empty",
            uploaded_files=[make_upload(image_upload_bytes)],
            prompts=[prompt],
            duration_seconds=3,
            aspect_ratio="16:9",
            concurrency_limit=1,
            confirmation="CONFIRM BATCH_EMPTY_PROMPT",
            expected_confirmation="CONFIRM BATCH_EMPTY_PROMPT",
        )


def test_prompt_over_5000_characters_is_rejected(app_config, image_upload_bytes) -> None:
    service = WorkbenchService(app_config)

    with pytest.raises(ValueError, match="at most 5000"):
        service.create_confirmed_batch(
            batch_id="BATCH_LONG_PROMPT",
            batch_name="long",
            uploaded_files=[make_upload(image_upload_bytes)],
            prompts=["x" * 5001],
            duration_seconds=3,
            aspect_ratio="16:9",
            concurrency_limit=1,
            confirmation="CONFIRM BATCH_LONG_PROMPT",
            expected_confirmation="CONFIRM BATCH_LONG_PROMPT",
        )


@pytest.mark.parametrize("name", ["not_image.txt", "fake.png"])
def test_invalid_image_content_is_rejected(app_config, name) -> None:
    service = WorkbenchService(app_config)

    with pytest.raises(ValueError, match="valid image"):
        service.create_confirmed_batch(
            batch_id=f"BATCH_BAD_IMAGE_{name.replace('.', '_').upper()}",
            batch_name="bad image",
            uploaded_files=[make_upload(b"not an image", name=name)],
            prompts=["normal prompt"],
            duration_seconds=3,
            aspect_ratio="16:9",
            concurrency_limit=1,
            confirmation=f"CONFIRM BATCH_BAD_IMAGE_{name.replace('.', '_').upper()}",
            expected_confirmation=f"CONFIRM BATCH_BAD_IMAGE_{name.replace('.', '_').upper()}",
        )


def test_image_over_15_mb_is_rejected_before_write(app_config, image_upload_bytes) -> None:
    service = WorkbenchService(app_config)

    with pytest.raises(ValueError, match="15 MB"):
        service.create_confirmed_batch(
            batch_id="BATCH_TOO_LARGE",
            batch_name="large",
            uploaded_files=[make_upload(image_upload_bytes, size=(15 * 1024 * 1024) + 1)],
            prompts=["normal prompt"],
            duration_seconds=3,
            aspect_ratio="16:9",
            concurrency_limit=1,
            confirmation="CONFIRM BATCH_TOO_LARGE",
            expected_confirmation="CONFIRM BATCH_TOO_LARGE",
        )


def test_batch_over_ten_tasks_is_rejected(app_config, sample_image) -> None:
    service = WorkbenchService(app_config)

    with pytest.raises(ValueError, match="At most 10 tasks"):
        create_batch(
            service,
            sample_image,
            batch_id="BATCH_TOO_MANY",
            prompts=["prompt"] * 11,
        )


@pytest.mark.parametrize(
    ("duration", "aspect_ratio", "message"),
    [(4, "16:9", "Duration"), (3, "4:3", "Aspect ratio")],
)
def test_unsupported_duration_or_aspect_ratio_is_rejected(
    app_config,
    sample_image,
    duration,
    aspect_ratio,
    message,
) -> None:
    service = WorkbenchService(app_config)

    with pytest.raises(ValueError, match=message):
        create_batch(
            service,
            sample_image,
            batch_id=f"BATCH_BAD_{duration}_{aspect_ratio.replace(':', '_')}",
            duration_seconds=duration,
            aspect_ratio=aspect_ratio,
        )


def test_path_traversal_batch_id_is_rejected(app_config, sample_image) -> None:
    service = WorkbenchService(app_config)

    with pytest.raises(ValueError, match="Batch ID"):
        create_batch(service, sample_image, batch_id="../escape")


def test_correct_confirmation_enqueues_tasks(app_config, image_upload_bytes) -> None:
    service = WorkbenchService(app_config)
    batch = service.create_confirmed_batch(
        batch_id="BATCH_CONFIRM_OK",
        batch_name="confirm ok",
        uploaded_files=[make_upload(image_upload_bytes)],
        prompts=["normal prompt"],
        duration_seconds=3,
        aspect_ratio="16:9",
        concurrency_limit=1,
        confirmation="CONFIRM BATCH_CONFIRM_OK",
        expected_confirmation="CONFIRM BATCH_CONFIRM_OK",
    )

    tasks = service.list_tasks(batch.id)
    assert len(tasks) == 1
    assert tasks[0].status.value == "QUEUED"


def test_wrong_confirmation_does_not_create_tasks(app_config, image_upload_bytes) -> None:
    service = WorkbenchService(app_config)

    with pytest.raises(ValueError, match="confirmation"):
        service.create_confirmed_batch(
            batch_id="BATCH_CONFIRM_BAD",
            batch_name="confirm bad",
            uploaded_files=[make_upload(image_upload_bytes)],
            prompts=["normal prompt"],
            duration_seconds=3,
            aspect_ratio="16:9",
            concurrency_limit=1,
            confirmation="WRONG",
            expected_confirmation="CONFIRM BATCH_CONFIRM_BAD",
        )

    assert service.get_batch("BATCH_CONFIRM_BAD") is None
    assert service.list_tasks("BATCH_CONFIRM_BAD") == []


def test_duplicate_confirmation_cannot_duplicate_tasks(app_config, image_upload_bytes) -> None:
    service = WorkbenchService(app_config)
    kwargs = {
        "batch_id": "BATCH_DUPLICATE",
        "batch_name": "duplicate",
        "prompts": ["normal prompt"],
        "duration_seconds": 3,
        "aspect_ratio": "16:9",
        "concurrency_limit": 1,
        "confirmation": "CONFIRM BATCH_DUPLICATE",
        "expected_confirmation": "CONFIRM BATCH_DUPLICATE",
    }
    service.create_confirmed_batch(uploaded_files=[make_upload(image_upload_bytes)], **kwargs)

    with pytest.raises(ValueError, match="already exists"):
        service.create_confirmed_batch(uploaded_files=[make_upload(image_upload_bytes)], **kwargs)

    assert len(service.list_tasks("BATCH_DUPLICATE")) == 1
