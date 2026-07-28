import asyncio

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import GenerationBatch, GenerationTask, VideoGenerationTaskDetail
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
from app.providers.video.volcengine_ark_provider import (
    VolcengineArkVideoGenerationProvider,
)
from app.services.file_storage import FileStorageService
from app.tasks.video_tasks import run_video_generation_task


def create_video_tasks(
    sessions: sessionmaker,
    count: int,
) -> list[int]:
    with sessions() as session:
        batch = GenerationBatch(
            batch_type=GenerationType.VIDEO,
            status=BatchStatus.PENDING,
            total_tasks=count,
        )
        tasks = [
            GenerationTask(
                batch=batch,
                task_type=GenerationType.VIDEO,
                status=TaskStatus.PENDING,
                prompt=f"video prompt {index}",
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
            for index in range(count)
        ]
        session.add_all(tasks)
        session.commit()
        return [task.id for task in tasks]


class LoopTrackingVideoProvider(VideoGenerationProvider):
    name = "loop-tracking"
    model = "loop-tracking-model"

    def __init__(self) -> None:
        self.created_loop = asyncio.get_running_loop()
        self.used_loop: asyncio.AbstractEventLoop | None = None
        self.closed_loop: asyncio.AbstractEventLoop | None = None
        self.client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"ok": True})
            )
        )

    async def generate(
        self,
        request: VideoGenerationRequest,
    ) -> VideoGenerationResult:
        self.used_loop = asyncio.get_running_loop()
        await self.client.get("https://provider.example.test/health")
        return VideoGenerationResult(
            provider_task_id=f"loop-task-{request.task_id}",
            content=MOCK_MP4,
        )

    async def close(self) -> None:
        self.closed_loop = asyncio.get_running_loop()
        await self.client.aclose()


def test_two_video_tasks_create_use_and_close_clients_in_their_own_loop(
    workspace_tmp_path,
) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    task_ids = create_video_tasks(sessions, 2)
    providers: list[LoopTrackingVideoProvider] = []

    def provider_factory() -> LoopTrackingVideoProvider:
        provider = LoopTrackingVideoProvider()
        providers.append(provider)
        return provider

    storage = FileStorageService(workspace_tmp_path)
    results = [
        run_video_generation_task(
            task_id,
            session_factory=sessions,
            provider_factory=provider_factory,
            storage=storage,
        )
        for task_id in task_ids
    ]

    assert [result["status"] for result in results] == ["SUCCESS", "SUCCESS"]
    assert len(providers) == 2
    assert providers[0] is not providers[1]
    assert providers[0].created_loop is not providers[1].created_loop
    for provider in providers:
        assert provider.created_loop is provider.used_loop
        assert provider.created_loop is provider.closed_loop
        assert provider.client.is_closed

    with sessions() as session:
        tasks = [session.get(GenerationTask, task_id) for task_id in task_ids]
        assert all(task is not None for task in tasks)
        assert [task.status for task in tasks if task is not None] == [
            TaskStatus.SUCCESS,
            TaskStatus.SUCCESS,
        ]


class ClosingTestArkProvider(VolcengineArkVideoGenerationProvider):
    async def close(self) -> None:
        await self.client.aclose()


def test_exhausted_poll_network_retries_persist_failed_task_details(
    workspace_tmp_path,
) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    task_id = create_video_tasks(sessions, 1)[0]
    request_counts = {"create": 0, "poll": 0}
    providers: list[ClosingTestArkProvider] = []

    async def no_sleep(_: float) -> None:
        return None

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            request_counts["create"] += 1
            return httpx.Response(200, json={"id": "ark-persisted-task"})
        request_counts["poll"] += 1
        raise httpx.ConnectError("poll unavailable", request=request)

    def provider_factory() -> ClosingTestArkProvider:
        provider = ClosingTestArkProvider(
            "test-key",
            "test-model",
            poll_network_retries=3,
            poll_retry_base_delay=2,
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            sleep=no_sleep,
        )
        providers.append(provider)
        return provider

    result = run_video_generation_task(
        task_id,
        session_factory=sessions,
        provider_factory=provider_factory,
        storage=FileStorageService(workspace_tmp_path),
    )

    assert result["status"] == "FAILED"
    assert request_counts == {"create": 1, "poll": 4}
    assert len(providers) == 1
    assert providers[0].client.is_closed
    with sessions() as session:
        task = session.get(GenerationTask, task_id)
        assert task is not None
        assert task.status == TaskStatus.FAILED
        assert task.error_code == "ARK_NETWORK_ERROR"
        assert task.provider == "volcengine_ark"
        assert task.model == "test-model"
        assert task.provider_task_id == "ark-persisted-task"
        assert task.batch.status == BatchStatus.FAILED
