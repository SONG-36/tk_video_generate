from __future__ import annotations

import pytest

from tk_video_generate.services.workbench_service import WorkbenchService


def test_confirmation_gate_blocks_unconfirmed_batch(app_config, sample_image) -> None:
    service = WorkbenchService(app_config)

    with pytest.raises(ValueError, match="Enter confirmation text exactly"):
        service.create_confirmed_batch(
            batch_id="BATCH_CONFIRM",
            batch_name="Confirm Test",
            uploaded_files=[],
            prompts=[],
            duration_seconds=3,
            aspect_ratio="16:9",
            concurrency_limit=1,
            confirmation="wrong",
            expected_confirmation="CONFIRM BATCH_CONFIRM",
        )


def test_batch_size_is_limited_to_ten(app_config, sample_image) -> None:
    service = WorkbenchService(app_config)

    with pytest.raises(ValueError, match="At most 10 tasks"):
        service.create_batch_from_paths(
            batch_id="BATCH_TOO_MANY",
            batch_name="Too Many",
            image_paths=[sample_image] * 11,
            prompts=["prompt"] * 11,
            duration_seconds=3,
            aspect_ratio="16:9",
            concurrency_limit=1,
        )
