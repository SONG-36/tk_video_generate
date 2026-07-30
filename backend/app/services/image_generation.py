import logging
from collections.abc import Sequence
from datetime import datetime

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.media.image_validation import ValidatedImage, validate_upload
from app.models.generation import (
    BatchStatus,
    GenerationBatch,
    GenerationTask,
    GenerationType,
    TaskStatus,
)
from app.models.image import (
    ImageGenerationTaskDetail,
    ImageOutputFormat,
    TaskReferenceImage,
)
from app.models.provider_usage import ProviderUsage, UsageSource
from app.models.result import GenerationResult, ResultType
from app.providers.image.base import ImageGenerationProvider, ImageGenerationRequest
from app.repositories.image_generation import ImageGenerationRepository
from app.schemas.image import ImageBatchCreate
from app.services.file_storage import FileStorageService

logger = logging.getLogger(__name__)


class ImageBatchService:
    def __init__(self, storage: FileStorageService | None = None):
        self.storage = storage or FileStorageService()

    async def create_batch(
        self,
        session: Session,
        payload: ImageBatchCreate,
        uploads_by_task: Sequence[Sequence[UploadFile]],
    ) -> GenerationBatch:
        if len(payload.tasks) != len(uploads_by_task):
            raise AppError("任务参数与上传文件不匹配", "BATCH_FILE_MISMATCH", 422)

        validated_groups: list[list[ValidatedImage]] = []
        for index, (task, uploads) in enumerate(zip(payload.tasks, uploads_by_task)):
            if len(uploads) > 5:
                raise AppError(
                    f"第 {index + 1} 个任务的参考图片不能超过 5 张",
                    "TOO_MANY_REFERENCE_IMAGES",
                    422,
                )
            if task.reference_images and len(task.reference_images) != len(uploads):
                raise AppError(
                    f"第 {index + 1} 个任务的参考图片参数不完整",
                    "REFERENCE_IMAGE_MISMATCH",
                    422,
                )
            validated_groups.append([await validate_upload(file) for file in uploads])

        saved_paths: list[str] = []
        try:
            batch = GenerationBatch(
                batch_type=GenerationType.IMAGE,
                status=BatchStatus.PENDING,
                total_tasks=len(payload.tasks),
                success_tasks=0,
                failed_tasks=0,
            )
            session.add(batch)
            session.flush()

            for task_input, images in zip(payload.tasks, validated_groups):
                task = GenerationTask(
                    batch_id=batch.id,
                    task_type=GenerationType.IMAGE,
                    status=TaskStatus.PENDING,
                    prompt=task_input.prompt,
                )
                task.image_detail = ImageGenerationTaskDetail(
                    aspect_ratio=task_input.aspect_ratio,
                    image_count=task_input.image_count,
                    output_format=ImageOutputFormat.PNG,
                )
                session.add(task)
                session.flush()
                for image in images:
                    relative_path, _ = self.storage.save_bytes(
                        f"uploads/image/{task.id}",
                        image.content,
                        image.extension,
                        prefix="reference-",
                    )
                    saved_paths.append(relative_path)
                    task.reference_images.append(
                        TaskReferenceImage(
                            file_path=relative_path,
                            file_name=image.original_name,
                            file_size=image.size,
                            mime_type=image.mime_type,
                        )
                    )
            session.flush()
        except Exception:
            session.rollback()
            for path in saved_paths:
                self.storage.try_delete(path, context="image_batch_flush")
            raise

        try:
            # commit 成功后文件已被数据库引用，因此提交之后不再执行可能触发文件补偿的 refresh。
            session.commit()
        except Exception:
            session.rollback()
            for path in saved_paths:
                self.storage.try_delete(path, context="image_batch_commit")
            raise
        return batch

    async def add_reference(
        self,
        session: Session,
        task_id: int,
        upload: UploadFile,
    ) -> TaskReferenceImage:
        repository = ImageGenerationRepository(session)
        task = repository.get_task(task_id)
        if task is None or task.task_type != GenerationType.IMAGE:
            raise AppError("图片任务不存在", "IMAGE_TASK_NOT_FOUND", 404)
        if task.status != TaskStatus.PENDING:
            raise AppError("只能为待执行任务上传参考图片", "TASK_NOT_PENDING", 409)
        if len(task.reference_images) >= 5:
            raise AppError("参考图片不能超过 5 张", "TOO_MANY_REFERENCE_IMAGES", 422)

        image = await validate_upload(upload)
        relative_path, _ = self.storage.save_bytes(
            f"uploads/image/{task.id}",
            image.content,
            image.extension,
            prefix="reference-",
        )
        reference = TaskReferenceImage(
            task_id=task.id,
            file_path=relative_path,
            file_name=image.original_name,
            file_size=image.size,
            mime_type=image.mime_type,
        )
        try:
            session.add(reference)
            session.flush()
            session.commit()
            return reference
        except Exception:
            session.rollback()
            self.storage.try_delete(relative_path, context="image_reference_write")
            raise


class ImageGenerationService:
    def __init__(
        self,
        provider: ImageGenerationProvider,
        storage: FileStorageService | None = None,
    ):
        self.provider = provider
        self.storage = storage or FileStorageService()

    async def execute(self, session: Session, task_id: int) -> GenerationTask:
        repository = ImageGenerationRepository(session)
        task = repository.get_task(task_id)
        if task is None or task.task_type != GenerationType.IMAGE:
            raise AppError("图片任务不存在", "IMAGE_TASK_NOT_FOUND", 404)
        if task.image_detail is None:
            raise AppError("图片任务参数缺失", "IMAGE_TASK_DETAIL_MISSING", 500)

        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        task.finished_at = None
        task.error_code = None
        task.error_message = None
        task.batch.status = BatchStatus.RUNNING
        session.commit()

        request = ImageGenerationRequest(
            task_id=task.id,
            prompt=task.prompt,
            aspect_ratio=task.image_detail.aspect_ratio,
            image_count=task.image_detail.image_count,
            output_format=task.image_detail.output_format,
            reference_paths=[
                self.storage.resolve_relative(reference.file_path)
                for reference in task.reference_images
            ],
        )
        result = await self.provider.generate(request)

        old_paths = [item.file_path for item in task.results]
        for item in list(task.results):
            session.delete(item)
        session.flush()

        saved_paths: list[str] = []
        try:
            for index, image in enumerate(result.images, start=1):
                relative_path, size = self.storage.save_bytes(
                    f"outputs/image/{task.id}",
                    image.content,
                    image.extension,
                    prefix=f"result-{index}-",
                )
                saved_paths.append(relative_path)
                task.results.append(
                    GenerationResult(
                        result_type=ResultType.IMAGE,
                        file_path=relative_path,
                        file_name=relative_path.rsplit("/", 1)[-1],
                        file_size=size,
                    )
                )

            task.provider = self.provider.name
            task.model = self.provider.model
            task.provider_task_id = result.provider_task_id
            task.status = TaskStatus.SUCCESS
            task.finished_at = datetime.now()
            self._record_usage(task, result.usage)
            self._refresh_batch(task.batch)
            session.commit()
        except Exception:
            session.rollback()
            for path in saved_paths:
                self.storage.try_delete(path, context="image_result_write")
            raise
        for path in old_paths:
            self.storage.try_delete(path, context="image_old_result")
        return task

    @staticmethod
    def mark_failed(session: Session, task_id: int, exc: Exception) -> None:
        repository = ImageGenerationRepository(session)
        task = repository.get_task(task_id)
        if task is None:
            return
        task.status = TaskStatus.FAILED
        task.error_code = (
            exc.code if isinstance(exc, AppError) else exc.__class__.__name__.upper()
        )
        task.error_message = str(exc)[:2000]
        task.finished_at = datetime.now()
        ImageGenerationService._refresh_batch(task.batch)
        session.commit()

    @staticmethod
    def _record_usage(task: GenerationTask, usage: object | None) -> None:
        values = {
            "provider": task.provider or "unknown",
            "model": task.model,
            "usage_source": UsageSource.UNKNOWN,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }
        if usage is not None:
            values.update(
                usage_source=UsageSource.PROVIDER,
                input_tokens=getattr(usage, "input_tokens", None),
                output_tokens=getattr(usage, "output_tokens", None),
                total_tokens=getattr(usage, "total_tokens", None),
            )
        if task.usage is None:
            task.usage = ProviderUsage(**values)
        else:
            for key, value in values.items():
                setattr(task.usage, key, value)

    @staticmethod
    def _refresh_batch(batch: GenerationBatch) -> None:
        statuses = [task.status for task in batch.tasks]
        batch.success_tasks = statuses.count(TaskStatus.SUCCESS)
        batch.failed_tasks = statuses.count(TaskStatus.FAILED)
        if statuses and all(status == TaskStatus.SUCCESS for status in statuses):
            batch.status = BatchStatus.SUCCESS
        elif statuses and all(status == TaskStatus.FAILED for status in statuses):
            batch.status = BatchStatus.FAILED
        elif all(status in {TaskStatus.SUCCESS, TaskStatus.FAILED} for status in statuses):
            batch.status = BatchStatus.PARTIAL_SUCCESS
        elif any(status == TaskStatus.RUNNING for status in statuses):
            batch.status = BatchStatus.RUNNING
        else:
            batch.status = BatchStatus.PENDING
