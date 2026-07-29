from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.generation import BatchStatus, TaskStatus
from app.models.image import ImageAspectRatio, ImageOutputFormat


class ImageBatchTaskCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=10000)
    aspect_ratio: ImageAspectRatio = ImageAspectRatio.PORTRAIT_9_16
    image_count: int = 1
    reference_images: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("提示词不能为空")
        return normalized

    @field_validator("image_count")
    @classmethod
    def validate_image_count(cls, value: int) -> int:
        if value not in {1, 2, 4}:
            raise ValueError("图片数量只能是 1、2 或 4")
        return value


class ImageBatchCreate(BaseModel):
    tasks: list[ImageBatchTaskCreate] = Field(min_length=1, max_length=10)


class ImageBatchTaskCreated(BaseModel):
    client_index: int
    task_id: int


class ImageBatchCreated(BaseModel):
    batch_id: int
    status: BatchStatus
    tasks: list[ImageBatchTaskCreated]


class ReferenceImageResponse(BaseModel):
    id: int
    task_id: int
    file_name: str
    file_size: int
    mime_type: str


class GenerationResultResponse(BaseModel):
    id: int
    file_name: str
    file_size: int
    preview_url: str
    download_url: str


class ImageTaskStatusResponse(BaseModel):
    id: int
    status: TaskStatus
    prompt: str
    aspect_ratio: ImageAspectRatio
    image_count: int
    output_format: ImageOutputFormat
    error_code: str | None
    error_message: str | None
    results: list[GenerationResultResponse]


class ImageBatchStatusResponse(BaseModel):
    batch_id: int
    status: BatchStatus
    total_tasks: int
    success_tasks: int
    failed_tasks: int
    created_at: datetime
    updated_at: datetime
    tasks: list[ImageTaskStatusResponse]

