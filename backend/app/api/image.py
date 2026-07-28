import json
from collections.abc import Callable

from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.core.database import get_db
from app.core.exceptions import AppError
from app.models.generation import GenerationType, TaskStatus
from app.repositories.image_generation import ImageGenerationRepository
from app.schemas.image import (
    GenerationResultResponse,
    ImageBatchCreate,
    ImageBatchCreated,
    ImageBatchStatusResponse,
    ImageBatchTaskCreated,
    ImageTaskStatusResponse,
    ReferenceImageResponse,
)
from app.services.image_generation import ImageBatchService, ImageGenerationService
from app.tasks.image_tasks import generate_image_task

router = APIRouter(prefix="/image")


def get_image_dispatcher() -> Callable[[int], object]:
    return generate_image_task.delay


@router.post("/batches", response_model=ImageBatchCreated, status_code=201)
async def create_image_batch(
    request: Request,
    session: Session = Depends(get_db),
    dispatch: Callable[[int], object] = Depends(get_image_dispatcher),
) -> ImageBatchCreated:
    form = await request.form()
    raw_payload = form.get("payload")
    if not isinstance(raw_payload, str):
        raise AppError("缺少批次 payload", "MISSING_BATCH_PAYLOAD", 422)
    try:
        payload = ImageBatchCreate.model_validate_json(raw_payload)
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

    batch = await ImageBatchService().create_batch(session, payload, uploads_by_task)
    task_ids = [task.id for task in batch.tasks]
    try:
        for task_id in task_ids:
            dispatch(task_id)
    except Exception as exc:
        for task_id in task_ids:
            ImageGenerationService.mark_failed(session, task_id, exc)
        raise AppError("异步任务投递失败", "TASK_DISPATCH_FAILED", 503) from exc

    return ImageBatchCreated(
        batch_id=batch.id,
        status=batch.status,
        tasks=[
            ImageBatchTaskCreated(client_index=index, task_id=task_id)
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
    reference = await ImageBatchService().add_reference(session, task_id, file)
    return ReferenceImageResponse(
        id=reference.id,
        task_id=reference.task_id,
        file_name=reference.file_name,
        file_size=reference.file_size,
        mime_type=reference.mime_type,
    )


@router.get("/batches/{batch_id}/status", response_model=ImageBatchStatusResponse)
def get_image_batch_status(
    batch_id: int,
    session: Session = Depends(get_db),
) -> ImageBatchStatusResponse:
    batch = ImageGenerationRepository(session).get_batch(batch_id)
    if batch is None or batch.batch_type != GenerationType.IMAGE:
        raise AppError("图片批次不存在", "IMAGE_BATCH_NOT_FOUND", 404)

    tasks: list[ImageTaskStatusResponse] = []
    for task in sorted(batch.tasks, key=lambda item: item.id):
        if task.image_detail is None:
            continue
        tasks.append(
            ImageTaskStatusResponse(
                id=task.id,
                status=task.status,
                prompt=task.prompt,
                aspect_ratio=task.image_detail.aspect_ratio,
                image_count=task.image_detail.image_count,
                output_format=task.image_detail.output_format,
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
    return ImageBatchStatusResponse(
        batch_id=batch.id,
        status=batch.status,
        total_tasks=batch.total_tasks,
        success_tasks=batch.success_tasks,
        failed_tasks=batch.failed_tasks,
        created_at=batch.created_at,
        updated_at=batch.updated_at,
        tasks=tasks,
    )

