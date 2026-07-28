import asyncio
import logging

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.core.exceptions import AppError
from app.models import GenerationBatch, GenerationTask, ImageGenerationTaskDetail
from app.models.generation import BatchStatus, GenerationType, TaskStatus
from app.models.image import ImageAspectRatio, ImageOutputFormat
from app.providers.image.base import (
    GeneratedImage,
    ImageGenerationProvider,
    ImageGenerationRequest,
    ImageGenerationResult,
)
from app.providers.image.mock import MOCK_PNG
from app.services.file_storage import FileStorageService
from app.tasks.image_tasks import run_image_generation_task


class TrackingSession(Session):
    was_closed = False

    def close(self) -> None:
        self.was_closed = True
        super().close()


def create_sessions() -> sessionmaker:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(
        bind=engine,
        class_=TrackingSession,
        expire_on_commit=False,
    )


def create_image_tasks(sessions: sessionmaker, count: int) -> list[int]:
    with sessions() as session:
        batch = GenerationBatch(
            batch_type=GenerationType.IMAGE,
            status=BatchStatus.PENDING,
            total_tasks=count,
        )
        tasks = [
            GenerationTask(
                batch=batch,
                task_type=GenerationType.IMAGE,
                status=TaskStatus.PENDING,
                prompt=f"image prompt {index}",
                image_detail=ImageGenerationTaskDetail(
                    aspect_ratio=ImageAspectRatio.PORTRAIT_9_16,
                    image_count=1,
                    output_format=ImageOutputFormat.PNG,
                ),
            )
            for index in range(count)
        ]
        session.add_all(tasks)
        session.commit()
        return [task.id for task in tasks]


def recording_session_factory(
    sessions: sessionmaker,
    created_sessions: list[TrackingSession],
):
    def create_session() -> TrackingSession:
        session = sessions()
        created_sessions.append(session)
        return session

    return create_session


class LoopTrackingImageProvider(ImageGenerationProvider):
    name = "loop-tracking"
    model = "loop-tracking-model"

    def __init__(self) -> None:
        self.created_loop = asyncio.get_running_loop()
        self.used_loop: asyncio.AbstractEventLoop | None = None
        self.closed_loop: asyncio.AbstractEventLoop | None = None
        self.generate_calls = 0
        self.close_calls = 0
        self.client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"ok": True})
            )
        )

    async def generate(
        self,
        request: ImageGenerationRequest,
    ) -> ImageGenerationResult:
        self.generate_calls += 1
        self.used_loop = asyncio.get_running_loop()
        await self.client.get("https://provider.example.test/health")
        return ImageGenerationResult(
            provider_task_id=f"loop-image-{request.task_id}",
            images=[GeneratedImage(MOCK_PNG)],
        )

    async def close(self) -> None:
        self.close_calls += 1
        self.closed_loop = asyncio.get_running_loop()
        await self.client.aclose()


def test_two_image_tasks_create_use_and_close_clients_in_their_own_loop(
    workspace_tmp_path,
) -> None:
    sessions = create_sessions()
    task_ids = create_image_tasks(sessions, 2)
    providers: list[LoopTrackingImageProvider] = []
    worker_sessions: list[TrackingSession] = []

    def provider_factory() -> LoopTrackingImageProvider:
        provider = LoopTrackingImageProvider()
        providers.append(provider)
        return provider

    storage = FileStorageService(workspace_tmp_path)
    results = [
        run_image_generation_task(
            task_id,
            session_factory=recording_session_factory(sessions, worker_sessions),
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
        assert provider.generate_calls == 1
        assert provider.close_calls == 1
        assert provider.client.is_closed
    assert len(worker_sessions) == 2
    assert all(session.was_closed for session in worker_sessions)

    with sessions() as session:
        tasks = [session.get(GenerationTask, task_id) for task_id in task_ids]
        assert all(task is not None for task in tasks)
        assert [task.status for task in tasks if task is not None] == [
            TaskStatus.SUCCESS,
            TaskStatus.SUCCESS,
        ]


def test_provider_initialization_failure_marks_task_failed_and_closes_session(
    workspace_tmp_path,
) -> None:
    sessions = create_sessions()
    task_id = create_image_tasks(sessions, 1)[0]
    worker_sessions: list[TrackingSession] = []
    factory_calls = 0

    def failing_provider_factory() -> ImageGenerationProvider:
        nonlocal factory_calls
        factory_calls += 1
        asyncio.get_running_loop()
        raise AppError(
            "provider initialization failed",
            "IMAGE_PROVIDER_INIT_FAILED",
            500,
        )

    result = run_image_generation_task(
        task_id,
        session_factory=recording_session_factory(sessions, worker_sessions),
        provider_factory=failing_provider_factory,
        storage=FileStorageService(workspace_tmp_path),
    )

    assert result == {
        "task_id": task_id,
        "status": "FAILED",
        "error": "provider initialization failed",
    }
    assert factory_calls == 1
    assert len(worker_sessions) == 1
    assert worker_sessions[0].was_closed
    with sessions() as session:
        task = session.get(GenerationTask, task_id)
        assert task is not None
        assert task.status == TaskStatus.FAILED
        assert task.error_code == "IMAGE_PROVIDER_INIT_FAILED"
        assert task.error_message == "provider initialization failed"
        assert task.batch.status == BatchStatus.FAILED


class CloseFailingImageProvider(ImageGenerationProvider):
    name = "close-failing"
    model = "close-failing-model"

    def __init__(self, generate_error: AppError | None = None) -> None:
        self.generate_error = generate_error
        self.generate_calls = 0
        self.close_calls = 0
        self.used_loop: asyncio.AbstractEventLoop | None = None
        self.closed_loop: asyncio.AbstractEventLoop | None = None

    async def generate(
        self,
        request: ImageGenerationRequest,
    ) -> ImageGenerationResult:
        self.generate_calls += 1
        self.used_loop = asyncio.get_running_loop()
        if self.generate_error is not None:
            raise self.generate_error
        return ImageGenerationResult(
            provider_task_id=f"close-failing-{request.task_id}",
            images=[GeneratedImage(MOCK_PNG)],
        )

    async def close(self) -> None:
        self.close_calls += 1
        self.closed_loop = asyncio.get_running_loop()
        raise RuntimeError("provider close failed")


def test_successful_generation_is_preserved_when_provider_close_fails(
    workspace_tmp_path,
    caplog,
) -> None:
    sessions = create_sessions()
    task_id = create_image_tasks(sessions, 1)[0]
    worker_sessions: list[TrackingSession] = []
    providers: list[CloseFailingImageProvider] = []

    def provider_factory() -> CloseFailingImageProvider:
        provider = CloseFailingImageProvider()
        providers.append(provider)
        return provider

    with caplog.at_level(logging.ERROR, logger="app.tasks.image_tasks"):
        result = run_image_generation_task(
            task_id,
            session_factory=recording_session_factory(sessions, worker_sessions),
            provider_factory=provider_factory,
            storage=FileStorageService(workspace_tmp_path),
        )

    assert result == {"task_id": task_id, "status": "SUCCESS", "result_count": 1}
    assert len(providers) == 1
    assert providers[0].generate_calls == 1
    assert providers[0].close_calls == 1
    assert providers[0].used_loop is providers[0].closed_loop
    assert len(worker_sessions) == 1
    assert worker_sessions[0].was_closed
    assert "Image provider cleanup failed" in caplog.text
    assert "stage=close" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "provider close failed" in caplog.text

    with sessions() as session:
        task = session.get(GenerationTask, task_id)
        assert task is not None
        assert task.status == TaskStatus.SUCCESS
        assert task.error_code is None
        assert len(task.results) == 1
        assert task.batch.status == BatchStatus.SUCCESS


def test_generation_failure_is_preserved_when_provider_close_also_fails(
    workspace_tmp_path,
    caplog,
) -> None:
    sessions = create_sessions()
    task_id = create_image_tasks(sessions, 1)[0]
    worker_sessions: list[TrackingSession] = []
    providers: list[CloseFailingImageProvider] = []

    def provider_factory() -> CloseFailingImageProvider:
        provider = CloseFailingImageProvider(
            AppError("primary generation failed", "IMAGE_GENERATE_FAILED", 502)
        )
        providers.append(provider)
        return provider

    with caplog.at_level(logging.ERROR, logger="app.tasks.image_tasks"):
        result = run_image_generation_task(
            task_id,
            session_factory=recording_session_factory(sessions, worker_sessions),
            provider_factory=provider_factory,
            storage=FileStorageService(workspace_tmp_path),
        )

    assert result == {
        "task_id": task_id,
        "status": "FAILED",
        "error": "primary generation failed",
    }
    assert len(providers) == 1
    assert providers[0].generate_calls == 1
    assert providers[0].close_calls == 1
    assert providers[0].used_loop is providers[0].closed_loop
    assert len(worker_sessions) == 1
    assert worker_sessions[0].was_closed
    assert "Image generation failed" in caplog.text
    assert "primary generation failed" in caplog.text
    assert "Image provider cleanup failed" in caplog.text
    assert "stage=close" in caplog.text
    assert "provider close failed" in caplog.text

    with sessions() as session:
        task = session.get(GenerationTask, task_id)
        assert task is not None
        assert task.status == TaskStatus.FAILED
        assert task.error_code == "IMAGE_GENERATE_FAILED"
        assert task.error_message == "primary generation failed"
        assert task.batch.status == BatchStatus.FAILED
