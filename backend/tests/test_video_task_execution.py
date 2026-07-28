from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import GenerationBatch, GenerationTask, VideoGenerationTaskDetail
from app.models.generation import BatchStatus, GenerationType, TaskStatus
from app.models.provider_usage import UsageSource
from app.models.video import (
    VideoAspectRatio,
    VideoDurationMode,
    VideoOutputFormat,
    VideoReferenceMode,
    VideoResolution,
)
from app.providers.video.base import VideoGenerationResult, VideoProviderUsage
from app.providers.video.mock import MOCK_MP4, MockVideoGenerationProvider
from app.services.file_storage import FileStorageService
from app.tasks.video_tasks import run_video_generation_task


class UsageVideoProvider(MockVideoGenerationProvider):
    name = "usage-test"
    model = "usage-test-model"

    async def generate(self, request) -> VideoGenerationResult:
        return VideoGenerationResult(
            provider_task_id=f"usage-video-{request.task_id}",
            content=MOCK_MP4,
            usage=VideoProviderUsage(
                input_tokens=10,
                output_tokens=20,
                total_tokens=30,
            ),
        )


def test_video_task_generates_playable_mp4_and_replaces_old_result(
    workspace_tmp_path,
) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as session:
        batch = GenerationBatch(
            batch_type=GenerationType.VIDEO,
            status=BatchStatus.PENDING,
            total_tasks=1,
        )
        task = GenerationTask(
            batch=batch,
            task_type=GenerationType.VIDEO,
            status=TaskStatus.PENDING,
            prompt="mock video prompt",
            video_detail=VideoGenerationTaskDetail(
                reference_mode=VideoReferenceMode.REFERENCE,
                resolution=VideoResolution.P720,
                aspect_ratio=VideoAspectRatio.PORTRAIT_9_16,
                duration_mode=VideoDurationMode.FIXED,
                fixed_duration=5,
                output_sound=False,
                output_format=VideoOutputFormat.MP4,
            ),
        )
        session.add(task)
        session.commit()
        task_id = task.id

    storage = FileStorageService(workspace_tmp_path)
    result = run_video_generation_task(
        task_id,
        session_factory=sessions,
        provider_factory=MockVideoGenerationProvider,
        storage=storage,
    )
    assert result == {"task_id": task_id, "status": "SUCCESS", "result_count": 1}

    with sessions() as session:
        task = session.get(GenerationTask, task_id)
        assert task is not None
        assert task.status == TaskStatus.SUCCESS
        assert task.batch.status == BatchStatus.SUCCESS
        assert len(task.results) == 1
        output = workspace_tmp_path / task.results[0].file_path
        assert output.read_bytes()[4:8] == b"ftyp"
        assert task.usage is not None
        assert task.usage.usage_source == UsageSource.UNKNOWN
        old_path = task.results[0].file_path

    rerun = run_video_generation_task(
        task_id,
        session_factory=sessions,
        provider_factory=MockVideoGenerationProvider,
        storage=storage,
    )
    assert rerun["status"] == "SUCCESS"
    with sessions() as session:
        task = session.get(GenerationTask, task_id)
        assert task is not None
        assert len(task.results) == 1
        assert task.results[0].file_path != old_path
        assert not (workspace_tmp_path / old_path).exists()

    usage_run = run_video_generation_task(
        task_id,
        session_factory=sessions,
        provider_factory=UsageVideoProvider,
        storage=storage,
    )
    assert usage_run["status"] == "SUCCESS"
    with sessions() as session:
        task = session.get(GenerationTask, task_id)
        assert task is not None and task.usage is not None
        assert task.usage.usage_source == UsageSource.PROVIDER
        assert task.usage.input_tokens == 10
        assert task.usage.output_tokens == 20
        assert task.usage.total_tokens == 30
