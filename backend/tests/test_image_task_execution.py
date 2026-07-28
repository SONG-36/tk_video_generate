from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models import GenerationBatch, GenerationTask, ImageGenerationTaskDetail
from app.models.generation import BatchStatus, GenerationType, TaskStatus
from app.models.image import ImageAspectRatio, ImageOutputFormat
from app.models.provider_usage import UsageSource
from app.providers.image.mock import MockImageGenerationProvider
from app.services.file_storage import FileStorageService
from app.tasks.image_tasks import run_image_generation_task


def test_image_task_generates_results_and_updates_batch(workspace_tmp_path) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as session:
        batch = GenerationBatch(
            batch_type=GenerationType.IMAGE,
            status=BatchStatus.PENDING,
            total_tasks=1,
        )
        task = GenerationTask(
            batch=batch,
            task_type=GenerationType.IMAGE,
            status=TaskStatus.PENDING,
            prompt="mock prompt",
            image_detail=ImageGenerationTaskDetail(
                aspect_ratio=ImageAspectRatio.PORTRAIT_9_16,
                image_count=4,
                output_format=ImageOutputFormat.PNG,
            ),
        )
        session.add(task)
        session.commit()
        task_id = task.id

    result = run_image_generation_task(
        task_id,
        session_factory=sessions,
        provider_factory=MockImageGenerationProvider,
        storage=FileStorageService(workspace_tmp_path),
    )
    assert result == {"task_id": task_id, "status": "SUCCESS", "result_count": 4}

    with sessions() as session:
        task = session.get(GenerationTask, task_id)
        assert task is not None
        assert task.status == TaskStatus.SUCCESS
        assert task.batch.status == BatchStatus.SUCCESS
        assert task.batch.success_tasks == 1
        assert len(task.results) == 4
        assert all((workspace_tmp_path / item.file_path).is_file() for item in task.results)
        assert task.usage is not None
        assert task.usage.usage_source == UsageSource.UNKNOWN
        old_paths = [item.file_path for item in task.results]

    rerun = run_image_generation_task(
        task_id,
        session_factory=sessions,
        provider_factory=MockImageGenerationProvider,
        storage=FileStorageService(workspace_tmp_path),
    )
    assert rerun["status"] == "SUCCESS"
    with sessions() as session:
        task = session.get(GenerationTask, task_id)
        assert task is not None
        assert len(task.results) == 4
        assert all(item.file_path not in old_paths for item in task.results)
        assert all(not (workspace_tmp_path / path).exists() for path in old_paths)
