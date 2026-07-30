import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import (
    GenerationBatch,
    GenerationTask,
    TaskReferenceImage,
    VideoGenerationTaskDetail,
)
from app.models.generation import BatchStatus, GenerationType, TaskStatus
from app.models.video import (
    VideoAspectRatio,
    VideoDurationMode,
    VideoOutputFormat,
    VideoReferenceMode,
    VideoResolution,
)
from app.providers.video.base import (
    VideoGenerationProvider,
    VideoGenerationRequest,
    VideoGenerationResult,
)
from app.providers.video.mock import MOCK_MP4
from app.services.file_storage import FileStorageService
from app.services.video_generation import VideoGenerationService


class CapturingVideoProvider(VideoGenerationProvider):
    name = "capture"
    model = "capture-model"

    def __init__(self) -> None:
        self.requests: list[VideoGenerationRequest] = []

    async def generate(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        self.requests.append(request)
        return VideoGenerationResult(
            provider_task_id=f"capture-{request.task_id}",
            content=MOCK_MP4,
        )


def create_task_with_references(
    sessions: sessionmaker,
    storage: FileStorageService,
    positions: list[int | None],
) -> tuple[int, list[str]]:
    with sessions() as session:
        task = GenerationTask(
            batch=GenerationBatch(
                batch_type=GenerationType.VIDEO,
                status=BatchStatus.PENDING,
                total_tasks=1,
            ),
            task_type=GenerationType.VIDEO,
            status=TaskStatus.PENDING,
            prompt="按图片顺序生成",
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
        for index, position in enumerate(positions):
            path, size = storage.save_bytes(
                f"uploads/video/{task.id}",
                f"reference-{index}".encode(),
                "png",
                prefix=f"source-{index}-",
            )
            paths.append(path)
            session.add(
                TaskReferenceImage(
                    task_id=task.id,
                    file_path=path,
                    file_name=f"reference-{index}.png",
                    file_size=size,
                    mime_type="image/png",
                    position=position,
                )
            )
        session.commit()
        return task.id, paths


def test_worker_orders_all_references_by_position(workspace_tmp_path) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    storage = FileStorageService(workspace_tmp_path)
    positions = [4, 2, 0, 3, 1]
    task_id, paths = create_task_with_references(sessions, storage, positions)
    provider = CapturingVideoProvider()

    with sessions() as session:
        asyncio.run(VideoGenerationService(provider, storage).execute(session, task_id))

    assert len(provider.requests) == 1
    expected = [paths[index] for index in [2, 4, 1, 3, 0]]
    assert [path.as_posix() for path in provider.requests[0].reference_paths] == [
        storage.resolve_relative(path).as_posix() for path in expected
    ]


def test_worker_orders_legacy_null_positions_by_primary_key(workspace_tmp_path) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    storage = FileStorageService(workspace_tmp_path)
    task_id, paths = create_task_with_references(sessions, storage, [None, None, None])
    provider = CapturingVideoProvider()

    with sessions() as session:
        asyncio.run(VideoGenerationService(provider, storage).execute(session, task_id))

    assert [path.as_posix() for path in provider.requests[0].reference_paths] == [
        storage.resolve_relative(path).as_posix() for path in paths
    ]
