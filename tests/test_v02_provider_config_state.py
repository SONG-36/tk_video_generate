from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from conftest import create_batch

from tk_video_generate.config import AppConfig
from tk_video_generate.enums import BatchStatus, ProviderName, TaskStatus
from tk_video_generate.providers.byteplus_seedance import BytePlusSeedanceProvider
from tk_video_generate.providers.factory import create_provider
from tk_video_generate.providers.mock_provider import MockVideoProvider
from tk_video_generate.repositories.sqlite_repository import SQLiteRepository
from tk_video_generate.services.state_machine import (
    InvalidStateTransitionError,
    ensure_transition_allowed,
)


def test_provider_factory_returns_mock_and_real_provider(app_config) -> None:
    assert isinstance(create_provider(ProviderName.MOCK.value, app_config), MockVideoProvider)
    assert isinstance(create_provider("byteplus_seedance", app_config), BytePlusSeedanceProvider)
    assert isinstance(create_provider("seedance", app_config), BytePlusSeedanceProvider)


def test_provider_factory_rejects_unknown_provider(app_config) -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        create_provider("unknown", app_config)


def test_mock_mode_does_not_require_seedance_key(app_config) -> None:
    provider = create_provider("mock", app_config)
    assert isinstance(provider, MockVideoProvider)
    assert app_config.seedance_config_status() == "Missing"


def test_seedance_config_missing_is_clear(app_config) -> None:
    with pytest.raises(ValueError, match="SEEDANCE_API_KEY"):
        app_config.validate_seedance_config()


def test_seedance_key_is_redacted_in_repr(tmp_path) -> None:
    config = AppConfig(
        project_root=tmp_path,
        database_path=tmp_path / "data" / "app.db",
        storage_dir=tmp_path / "storage",
        uploads_dir=tmp_path / "storage/uploads",
        outputs_dir=tmp_path / "storage/outputs",
        archives_dir=tmp_path / "storage/archives",
        seedance_api_key="secret-key",
        seedance_model="seedance-test",
    )

    rendered = repr(config)

    assert "secret-key" not in rendered
    assert "[REDACTED]" in rendered


def test_legacy_v01_database_migrates_idempotently(tmp_path) -> None:
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE batches (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            provider TEXT NOT NULL,
            concurrency_limit INTEGER NOT NULL,
            confirmation_text TEXT NOT NULL,
            total_tasks INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            name TEXT NOT NULL,
            image_path TEXT NOT NULL,
            prompt TEXT NOT NULL,
            provider TEXT NOT NULL,
            duration_seconds INTEGER NOT NULL,
            aspect_ratio TEXT NOT NULL,
            status TEXT NOT NULL,
            progress INTEGER NOT NULL,
            provider_task_id TEXT,
            output_video_path TEXT,
            request_json_path TEXT,
            result_json_path TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            error_code TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        );
        INSERT INTO batches VALUES ('BATCH_LEGACY', 'legacy', 'mock', 1, 'CONFIRM', 1, 'now');
        INSERT INTO tasks VALUES (
            'TASK_LEGACY', 'BATCH_LEGACY', 'Task', 'image.png', 'prompt', 'mock',
            3, '16:9', 'COMPLETED', 100, 'provider-id', 'video.mp4',
            'request.json', 'result.json', 0, NULL, NULL, 'now', 'now', 'now'
        );
        """
    )
    conn.commit()
    conn.close()

    repo = SQLiteRepository(db)
    repo.initialize()

    batch = repo.get_batch("BATCH_LEGACY")
    task = repo.get_task("TASK_LEGACY")
    assert batch.status is BatchStatus.COMPLETED
    assert task.status is TaskStatus.SUCCEEDED
    assert task.provider_task_id == "provider-id"
    assert hasattr(task, "provider_status")
    assert hasattr(task, "image_url")
    assert task.image_url is None


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskStatus.QUEUED, TaskStatus.SUBMITTING),
        (TaskStatus.SUBMITTING, TaskStatus.SUBMITTED),
        (TaskStatus.SUBMITTED, TaskStatus.POLLING),
        (TaskStatus.POLLING, TaskStatus.DOWNLOADING),
        (TaskStatus.DOWNLOADING, TaskStatus.SUCCEEDED),
    ],
)
def test_real_task_state_machine_allows_expected_path(current, target) -> None:
    ensure_transition_allowed(current, target)


def test_state_machine_rejects_illegal_jump_and_task_does_not_use_batch_completed() -> None:
    with pytest.raises(InvalidStateTransitionError):
        ensure_transition_allowed(TaskStatus.QUEUED, TaskStatus.SUCCEEDED)

    assert "COMPLETED" not in {status.value for status in TaskStatus}


def test_new_provider_fields_are_persisted(app_config, sample_image) -> None:
    service = __import__(
        "tk_video_generate.services.workbench_service",
        fromlist=["WorkbenchService"],
    ).WorkbenchService(app_config)
    batch = create_batch(service, sample_image, batch_id="BATCH_PROVIDER_FIELDS")
    task = service.list_tasks(batch.id)[0]

    service.repository.mark_submitted(
        task.id,
        "remote-task-id",
        Path(task.image_path),
        Path(task.image_path),
        "2026-07-24T00:00:00+00:00",
        "2026-07-24T00:00:10+00:00",
    )
    persisted = service.get_task(task.id)

    assert persisted.provider_task_id == "remote-task-id"
    assert persisted.provider_status == "submitted"
    assert persisted.submitted_at == "2026-07-24T00:00:00+00:00"
    assert persisted.image_url is None
