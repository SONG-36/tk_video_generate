import json
from collections.abc import Callable

from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.core.database import get_db
from app.core.exceptions import AppError
from app.models.generation import GenerationType
from app.repositories.video_generation import VideoGenerationRepository
from app.schemas.image import GenerationResultResponse, ReferenceImageResponse
from app.schemas.video import (
    VideoBatchCreate,
    VideoBatchCreated,
    VideoBatchStatusResponse,
    VideoBatchTaskCreated,
    VideoTaskStatusResponse,
)
from app.services.video_generation import VideoBatchService, VideoGenerationService
from app.tasks.video_tasks import generate_video_task

router = APIRouter(prefix="/video")


def get_video_dispatcher() -> Callable[[int], object]:
    return generate_video_task.delay


@router.post("/batches", response_model=VideoBatchCreated, status_code=201)
async def create_video_batch(
    request: Request,
    session: Session = Depends(get_db),
    dispatch: Callable[[int], object] = Depends(get_video_dispatcher),
) -> VideoBatchCreated:
    form = await request.form()
    raw_payload = form.get("payload")
    if not isinstance(raw_payload, str):
        raise AppError("缺少批次 payload", "MISSING_BATCH_PAYLOAD", 422)
    try:
        payload = VideoBatchCreate.model_validate_json(raw_payload)
    except (ValidationError, json.JSONDecodeError) as exc:
        raise AppError("批次参数不合法", "INVALID_BATCH_PAYLOAD", 422) from exc

    uploads_by_task: list[list[UploadFile]] = []
    for index in range(len(payload.tasks)):
        uploads = [
            item
            for item in form.getlist(f"references_{index}")
            if isinstance(item, StarletteUploadFile)
        ]
        uploads_by_task.append(uploads)

    batch = await VideoBatchService().create_batch(session, payload, uploads_by_task)
    task_ids = [task.id for task in batch.tasks]
    try:
        for task_id in task_ids:
            dispatch(task_id)
    except Exception as exc:
        for task_id in task_ids:
            VideoGenerationService.mark_failed(session, task_id, exc)
        raise AppError("异步任务投递失败", "TASK_DISPATCH_FAILED", 503) from exc

    return VideoBatchCreated(
        batch_id=batch.id,
        status=batch.status,
        tasks=[
            VideoBatchTaskCreated(client_index=index, task_id=task_id)
            for index, task_id in enumerate(task_ids)
        ],
    )


@router.post(
    "/tasks/{task_id}/references",
    response_model=ReferenceImageResponse,
    status_code=201,
)
async def upload_reference_image(
    task_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_db),
) -> ReferenceImageResponse:
    reference = await VideoBatchService().add_reference(session, task_id, file)
    return ReferenceImageResponse(
        id=reference.id,
        task_id=reference.task_id,
        file_name=reference.file_name,
        file_size=reference.file_size,
        mime_type=reference.mime_type,
    )


@router.get("/batches/{batch_id}/status", response_model=VideoBatchStatusResponse)
def get_video_batch_status(
    batch_id: int,
    session: Session = Depends(get_db),
) -> VideoBatchStatusResponse:
    batch = VideoGenerationRepository(session).get_batch(batch_id)
    if batch is None or batch.batch_type != GenerationType.VIDEO:
        raise AppError("视频批次不存在", "VIDEO_BATCH_NOT_FOUND", 404)

    tasks: list[VideoTaskStatusResponse] = []
    for task in sorted(batch.tasks, key=lambda item: item.id):
        if task.video_detail is None:
            continue
        detail = task.video_detail
        tasks.append(
            VideoTaskStatusResponse(
                id=task.id,
                status=task.status,
                prompt=task.prompt,
                reference_mode=detail.reference_mode,
                resolution=detail.resolution,
                aspect_ratio=detail.aspect_ratio,
                duration_mode=detail.duration_mode,
                fixed_duration=detail.fixed_duration,
                output_sound=detail.output_sound,
                output_format=detail.output_format,
                model=detail.model,
                error_code=task.error_code,
                error_message=task.error_message,
                results=[
                    GenerationResultResponse(
                        id=result.id,
                        file_name=result.file_name,
                        file_size=result.file_size,
                        preview_url=f"/api/files/download/{result.id}?inline=true",
                        download_url=f"/api/files/download/{result.id}",
                    )
                    for result in sorted(task.results, key=lambda item: item.id)
                ],
            )
        )
    return VideoBatchStatusResponse(
        batch_id=batch.id,
        status=batch.status,
        total_tasks=batch.total_tasks,
        success_tasks=batch.success_tasks,
        failed_tasks=batch.failed_tasks,
        created_at=batch.created_at,
        updated_at=batch.updated_at,
        tasks=tasks,
    )
