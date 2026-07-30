import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from starlette.datastructures import Headers

from app.core.database import Base
from app.core.exceptions import AppError
from app.models import GenerationBatch, GenerationTask, TaskReferenceImage
from app.models.generation import BatchStatus, GenerationType, TaskStatus
from app.models.video import (
    VideoAspectRatio,
    VideoDurationMode,
    VideoGenerationTaskDetail,
    VideoOutputFormat,
    VideoReferenceMode,
    VideoResolution,
)
from app.schemas.video import VideoBatchCreate
from app.repositories.video_generation import VideoGenerationRepository
from app.services.file_storage import FileStorageService
from app.services.video_generation import (
    VideoBatchService,
    normalize_video_reference_positions,
)
from tests.image_helpers import create_png_bytes


def upload(name: str = "reference.png") -> UploadFile:
    content = create_png_bytes()
    return UploadFile(
        BytesIO(content),
        size=len(content),
        filename=name,
        headers=Headers({"content-type": "image/png"}),
    )


def sessions() -> sessionmaker[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def payload(image_names: list[str]) -> VideoBatchCreate:
    return VideoBatchCreate.model_validate(
        {
            "tasks": [
                {
                    "prompt": "让@图片1进入镜头",
                    "reference_mode": "REFERENCE",
                    "resolution": "720P",
                    "aspect_ratio": "9:16",
                    "duration_mode": "SMART",
                    "reference_images": image_names,
                }
            ]
        }
    )


def create_pending_task(
    session: Session,
    storage: FileStorageService,
    positions: list[int | None] | None = None,
) -> tuple[int, list[str]]:
    batch = GenerationBatch(
        batch_type=GenerationType.VIDEO,
        status=BatchStatus.PENDING,
        total_tasks=1,
    )
    task = GenerationTask(
        batch=batch,
        task_type=GenerationType.VIDEO,
        status=TaskStatus.PENDING,
        prompt="测试追加",
        video_detail=VideoGenerationTaskDetail(
            reference_mode=VideoReferenceMode.REFERENCE,
            resolution=VideoResolution.P720,
            aspect_ratio=VideoAspectRatio.PORTRAIT_9_16,
            duration_mode=VideoDurationMode.SMART,
            fixed_duration=None,
            output_sound=False,
            output_format=VideoOutputFormat.MP4,
        ),
    )
    session.add(task)
    session.flush()
    paths: list[str] = []
    for index, position in enumerate(positions or []):
        path, size = storage.save_bytes(
            f"uploads/video/{task.id}",
            create_png_bytes(),
            "png",
            prefix=f"history-{index}-",
        )
        paths.append(path)
        task.reference_images.append(
            TaskReferenceImage(
                file_path=path,
                file_name=f"history-{index}.png",
                file_size=size,
                mime_type="image/png",
                position=position,
            )
        )
    session.commit()
    return task.id, paths


def test_batch_commit_failure_cleans_new_files(
    workspace_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = sessions()
    storage = FileStorageService(workspace_tmp_path)
    with session_factory() as session:
        monkeypatch.setattr(
            session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failed"))
        )
        with pytest.raises(RuntimeError, match="commit failed"):
            asyncio.run(
                VideoBatchService(storage).create_batch(
                    session, payload(["one.png"]), [[upload("one.png")]]
                )
            )
    assert list(workspace_tmp_path.rglob("*.png")) == []


def test_batch_commit_success_does_not_refresh_or_delete_files(
    workspace_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = sessions()
    storage = FileStorageService(workspace_tmp_path)
    with session_factory() as session:
        monkeypatch.setattr(
            session,
            "refresh",
            lambda *_: (_ for _ in ()).throw(RuntimeError("refresh must not run")),
        )
        batch = asyncio.run(
            VideoBatchService(storage).create_batch(
                session, payload(["one.png"]), [[upload("one.png")]]
            )
        )
        assert batch.id is not None
    assert len(list(workspace_tmp_path.rglob("*.png"))) == 1


def test_add_reference_commit_failure_cleans_only_new_file(
    workspace_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = sessions()
    storage = FileStorageService(workspace_tmp_path)
    with session_factory() as session:
        task_id, historical_paths = create_pending_task(session, storage, [None])
        historical_file = storage.resolve_relative(historical_paths[0])
        monkeypatch.setattr(
            session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failed"))
        )
        with pytest.raises(RuntimeError, match="commit failed"):
            asyncio.run(
                VideoBatchService(storage).add_reference(
                    session, task_id, upload("new.png")
                )
            )
        assert historical_file.exists()
    assert len(list(workspace_tmp_path.rglob("*.png"))) == 1


def test_add_reference_commit_success_does_not_refresh(
    workspace_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = sessions()
    storage = FileStorageService(workspace_tmp_path)
    with session_factory() as session:
        task_id, _ = create_pending_task(session, storage)
        monkeypatch.setattr(
            session,
            "refresh",
            lambda *_: (_ for _ in ()).throw(RuntimeError("refresh must not run")),
        )
        reference = asyncio.run(
            VideoBatchService(storage).add_reference(
                session, task_id, upload("new.png")
            )
        )
        assert reference.position == 0
        assert storage.resolve_relative(reference.file_path).exists()


def test_partial_file_is_removed_when_write_fails(
    workspace_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = FileStorageService(workspace_tmp_path)

    def partial_write(path: Path, content: bytes) -> int:
        with path.open("wb") as stream:
            stream.write(content[:4])
        raise OSError("disk failed")

    monkeypatch.setattr(Path, "write_bytes", partial_write)
    with pytest.raises(OSError, match="disk failed"):
        storage.save_bytes("uploads/video/1", b"complete-content", "png")
    assert list(workspace_tmp_path.rglob("*.png")) == []


def test_batch_mid_write_failure_cleans_completed_and_partial_files(
    workspace_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = sessions()
    storage = FileStorageService(workspace_tmp_path)
    original_write = Path.write_bytes
    write_count = 0

    def fail_second_write(path: Path, content: bytes) -> int:
        nonlocal write_count
        write_count += 1
        if write_count == 2:
            with path.open("wb") as stream:
                stream.write(content[:4])
            raise OSError("second write failed")
        return original_write(path, content)

    monkeypatch.setattr(Path, "write_bytes", fail_second_write)
    with session_factory() as session:
        with pytest.raises(OSError, match="second write failed"):
            asyncio.run(
                VideoBatchService(storage).create_batch(
                    session,
                    payload(["one.png", "two.png"]),
                    [[upload("one.png"), upload("two.png")]],
                )
            )
    assert list(workspace_tmp_path.rglob("*.png")) == []


def test_add_partial_write_failure_keeps_historical_file(
    workspace_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = sessions()
    storage = FileStorageService(workspace_tmp_path)
    with session_factory() as session:
        task_id, historical_paths = create_pending_task(session, storage, [None])
        historical_file = storage.resolve_relative(historical_paths[0])

        def partial_write(path: Path, content: bytes) -> int:
            with path.open("wb") as stream:
                stream.write(content[:4])
            raise OSError("append write failed")

        monkeypatch.setattr(Path, "write_bytes", partial_write)
        with pytest.raises(OSError, match="append write failed"):
            asyncio.run(
                VideoBatchService(storage).add_reference(
                    session, task_id, upload("new.png")
                )
            )
        assert historical_file.exists()
    assert len(list(workspace_tmp_path.rglob("*.png"))) == 1


def test_unique_position_conflict_is_mapped_and_new_file_is_cleaned(
    workspace_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = sessions()
    storage = FileStorageService(workspace_tmp_path)
    with session_factory() as session:
        task_id, _ = create_pending_task(session, storage)
        original_flush = session.flush
        def conflicting_flush(*args, **kwargs) -> None:
            if any(isinstance(item, TaskReferenceImage) for item in session.new):
                raise IntegrityError("insert", {}, RuntimeError("duplicate"))
            original_flush(*args, **kwargs)

        monkeypatch.setattr(session, "flush", conflicting_flush)
        with pytest.raises(AppError) as raised:
            asyncio.run(
                VideoBatchService(storage).add_reference(
                    session, task_id, upload("new.png")
                )
            )
        assert raised.value.code == "REFERENCE_IMAGE_POSITION_CONFLICT"
        assert raised.value.status_code == 409
    assert list(workspace_tmp_path.rglob("reference-*.png")) == []


def test_repository_uses_mysql_task_row_lock_for_append() -> None:
    captured = []

    class CapturingSession:
        def scalar(self, statement):
            captured.append(statement)
            return None

    VideoGenerationRepository(CapturingSession()).get_task(1, for_update=True)  # type: ignore[arg-type]
    sql = str(captured[0].compile(dialect=mysql.dialect()))
    assert "FOR UPDATE" in sql


def test_two_serialized_appends_receive_distinct_contiguous_positions(
    workspace_tmp_path: Path,
) -> None:
    session_factory = sessions()
    storage = FileStorageService(workspace_tmp_path)
    with session_factory() as session:
        task_id, _ = create_pending_task(session, storage)
        first = asyncio.run(
            VideoBatchService(storage).add_reference(
                session, task_id, upload("first.png")
            )
        )
        second = asyncio.run(
            VideoBatchService(storage).add_reference(
                session, task_id, upload("second.png")
            )
        )
        assert [first.position, second.position] == [0, 1]


def test_mixed_and_null_positions_are_compacted_idempotently_before_append(
    workspace_tmp_path: Path,
) -> None:
    session_factory = sessions()
    storage = FileStorageService(workspace_tmp_path)
    with session_factory() as session:
        task_id, _ = create_pending_task(session, storage, [2, None, 0])
        task = session.get(GenerationTask, task_id)
        assert task is not None
        first = normalize_video_reference_positions(session, task.reference_images)
        second = normalize_video_reference_positions(session, task.reference_images)
        assert [item.id for item in second] == [item.id for item in first]
        assert [item.position for item in second] == [0, 1, 2]
        session.rollback()

        added = asyncio.run(
            VideoBatchService(storage).add_reference(
                session, task_id, upload("new.png")
            )
        )
        references = session.scalars(
            select(TaskReferenceImage)
            .where(TaskReferenceImage.task_id == task_id)
            .order_by(TaskReferenceImage.position)
        ).all()
        assert [item.position for item in references] == [0, 1, 2, 3]
        assert added.position == 3
