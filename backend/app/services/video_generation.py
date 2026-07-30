import logging
from collections.abc import Sequence
from datetime import datetime

from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError
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
from app.models.image import TaskReferenceImage
from app.models.provider_usage import ProviderUsage, UsageSource
from app.models.result import GenerationResult, ResultType
from app.models.video import (
    VideoGenerationTaskDetail,
    VideoOutputFormat,
    VideoReferenceMode,
)
from app.providers.video.base import (
    VideoGenerationProvider,
    VideoGenerationRequest,
    VideoProviderUsage,
)
from app.repositories.video_generation import VideoGenerationRepository
from app.schemas.video import VideoBatchCreate
from app.services.file_storage import FileStorageService
from app.services.video_prompt import (
    VideoPromptReferenceError,
    normalize_video_prompt,
)

logger = logging.getLogger(__name__)


def ordered_video_references(
    references: Sequence[TaskReferenceImage],
) -> list[TaskReferenceImage]:
    """新数据按 position 排序，历史 NULL 数据稳定回退到主键顺序。"""
    return sorted(
        references,
        key=lambda reference: (
            reference.position is None,
            reference.position if reference.position is not None else 0,
            reference.id or 0,
        ),
    )


def normalize_video_reference_positions(
    session: Session,
    references: Sequence[TaskReferenceImage],
) -> list[TaskReferenceImage]:
    """将兼容排序结果幂等地压实为连续的 0 基 position。"""
    ordered = ordered_video_references(references)
    if all(reference.position == index for index, reference in enumerate(ordered)):
        return ordered
    # 先统一置 NULL，避免部分旧 position 在原地重排时触发瞬时唯一键冲突。
    for reference in ordered:
        reference.position = None
    session.flush()
    for position, reference in enumerate(ordered):
        reference.position = position
    session.flush()
    return ordered


class VideoBatchService:
    def __init__(self, storage: FileStorageService | None = None):
        self.storage = storage or FileStorageService()

    async def create_batch(
        self,
        session: Session,
        payload: VideoBatchCreate,
        uploads_by_task: Sequence[Sequence[UploadFile]],
    ) -> GenerationBatch:
        if len(payload.tasks) != len(uploads_by_task):
            raise AppError(
                "任务参数与上传文件不匹配", "BATCH_FILE_MISMATCH", 422
            )

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
            if task.reference_mode == VideoReferenceMode.FIRST_FRAME and len(uploads) != 1:
                raise AppError(
                    f"第 {index + 1} 个任务的首帧图必须且只能上传 1 张",
                    "FIRST_FRAME_IMAGE_REQUIRED",
                    422,
                )
            try:
                # 前端校验用于即时反馈；实际图片数量以服务端收到的上传文件为准。
                task.prompt = normalize_video_prompt(task.prompt, len(uploads))
            except VideoPromptReferenceError as exc:
                raise AppError(str(exc), "INVALID_VIDEO_IMAGE_REFERENCE", 422) from exc
            validated_groups.append([await validate_upload(file) for file in uploads])

        saved_paths: list[str] = []
        try:
            batch = GenerationBatch(
                batch_type=GenerationType.VIDEO,
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
                    task_type=GenerationType.VIDEO,
                    status=TaskStatus.PENDING,
                    prompt=task_input.prompt,
                )
                task.video_detail = VideoGenerationTaskDetail(
                    reference_mode=task_input.reference_mode,
                    resolution=task_input.resolution,
                    aspect_ratio=task_input.aspect_ratio,
                    duration_mode=task_input.duration_mode,
                    fixed_duration=task_input.fixed_duration,
                    output_sound=task_input.output_sound,
                    output_format=VideoOutputFormat.MP4,
                    model=task_input.model.value,
                )
                session.add(task)
                session.flush()
                for position, image in enumerate(images):
                    relative_path, _ = self.storage.save_bytes(
                        f"uploads/video/{task.id}",
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
                            position=position,
                        )
                    )
            session.flush()
        except Exception:
            session.rollback()
            for path in saved_paths:
                self.storage.try_delete(path, context="video_batch_flush")
            raise

        try:
            # commit 是文件补偿边界：返回成功后数据库已引用这些文件，后续不得再删除。
            session.commit()
        except Exception:
            session.rollback()
            for path in saved_paths:
                self.storage.try_delete(path, context="video_batch_commit")
            raise
        return batch

    async def add_reference(
        self,
        session: Session,
        task_id: int,
        upload: UploadFile,
    ) -> TaskReferenceImage:
        # 锁定任务行，使补齐历史位置、计算下一个位置和插入处于同一串行事务。
        task = VideoGenerationRepository(session).get_task(task_id, for_update=True)
        if task is None or task.task_type != GenerationType.VIDEO:
            raise AppError("视频任务不存在", "VIDEO_TASK_NOT_FOUND", 404)
        if task.status != TaskStatus.PENDING:
            raise AppError("只能为待执行任务上传参考图片", "TASK_NOT_PENDING", 409)
        if task.video_detail is None:
            raise AppError("视频任务参数缺失", "VIDEO_TASK_DETAIL_MISSING", 500)
        limit = (
            1
            if task.video_detail.reference_mode == VideoReferenceMode.FIRST_FRAME
            else 5
        )
        if len(task.reference_images) >= limit:
            raise AppError(
                f"当前模式参考图片不能超过 {limit} 张",
                "TOO_MANY_REFERENCE_IMAGES",
                422,
            )

        relative_path: str | None = None
        try:
            ordered_existing = normalize_video_reference_positions(
                session, task.reference_images
            )

            image = await validate_upload(upload)
            relative_path, _ = self.storage.save_bytes(
                f"uploads/video/{task.id}",
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
                position=len(ordered_existing),
            )
            session.add(reference)
            session.flush()
            session.commit()
            return reference
        except IntegrityError as exc:
            session.rollback()
            if relative_path is not None:
                self.storage.try_delete(relative_path, context="video_reference_conflict")
            raise AppError(
                "参考图片顺序发生并发冲突，请重试",
                "REFERENCE_IMAGE_POSITION_CONFLICT",
                409,
            ) from exc
        except Exception:
            session.rollback()
            if relative_path is not None:
                self.storage.try_delete(relative_path, context="video_reference_write")
            raise


class VideoGenerationService:
    def __init__(
        self,
        provider: VideoGenerationProvider,
        storage: FileStorageService | None = None,
    ):
        self.provider = provider
        self.storage = storage or FileStorageService()

    async def execute(self, session: Session, task_id: int) -> GenerationTask:
        task = VideoGenerationRepository(session).get_task(task_id)
        if task is None or task.task_type != GenerationType.VIDEO:
            raise AppError("视频任务不存在", "VIDEO_TASK_NOT_FOUND", 404)
        if task.video_detail is None:
            raise AppError("视频任务参数缺失", "VIDEO_TASK_DETAIL_MISSING", 500)

        detail = task.video_detail
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        task.finished_at = None
        task.error_code = None
        task.error_message = None
        task.batch.status = BatchStatus.RUNNING
        session.commit()

        request = VideoGenerationRequest(
            task_id=task.id,
            prompt=task.prompt,
            reference_mode=detail.reference_mode,
            resolution=detail.resolution,
            aspect_ratio=detail.aspect_ratio,
            duration_mode=detail.duration_mode,
            fixed_duration=detail.fixed_duration,
            output_sound=detail.output_sound,
            output_format=detail.output_format,
            model=detail.model,
            reference_paths=[
                self.storage.resolve_relative(reference.file_path)
                for reference in ordered_video_references(task.reference_images)
            ],
        )
        result = await self.provider.generate(request)

        old_paths = [item.file_path for item in task.results]
        for item in list(task.results):
            session.delete(item)
        session.flush()

        saved_paths: list[str] = []
        try:
            relative_path, size = self.storage.save_bytes(
                f"outputs/video/{task.id}",
                result.content,
                result.extension,
                prefix="result-",
            )
            saved_paths.append(relative_path)
            task.results.append(
                GenerationResult(
                    result_type=ResultType.VIDEO,
                    file_path=relative_path,
                    file_name=relative_path.rsplit("/", 1)[-1],
                    file_size=size,
                )
            )
            task.provider = self.provider.name
            task.model = request.model
            task.provider_task_id = result.provider_task_id
            task.status = TaskStatus.SUCCESS
            task.finished_at = datetime.now()
            self._record_usage(task, result.usage)
            self._refresh_batch(task.batch)
            session.commit()
        except Exception:
            session.rollback()
            for path in saved_paths:
                self.storage.try_delete(path, context="video_result_write")
            raise
        # 新结果提交成功后再清理旧文件；清理失败不能回滚已提交数据或误删新结果。
        for path in old_paths:
            self.storage.try_delete(path, context="video_old_result")
        return task

    @staticmethod
    def mark_failed(
        session: Session,
        task_id: int,
        exc: Exception,
        provider: str | None = None,
        model: str | None = None,
        provider_task_id: str | None = None,
    ) -> None:
        task = VideoGenerationRepository(session).get_task(task_id)
        if task is None:
            return
        if provider:
            task.provider = provider
        if model:
            task.model = model
        elif task.video_detail is not None:
            task.model = task.video_detail.model
        if provider_task_id:
            task.provider_task_id = provider_task_id
        task.status = TaskStatus.FAILED
        task.error_code = (
            exc.code if isinstance(exc, AppError) else exc.__class__.__name__.upper()
        )
        task.error_message = str(exc)[:2000]
        task.finished_at = datetime.now()
        VideoGenerationService._refresh_batch(task.batch)
        session.commit()

    @staticmethod
    def _record_usage(
        task: GenerationTask,
        usage: VideoProviderUsage | None,
    ) -> None:
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
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
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
