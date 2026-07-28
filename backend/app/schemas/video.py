from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.generation import BatchStatus, TaskStatus
from app.models.video import (
    VideoAspectRatio,
    VideoDurationMode,
    VideoOutputFormat,
    VideoReferenceMode,
    VideoResolution,
)
from app.schemas.image import GenerationResultResponse


class VideoBatchTaskCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    reference_mode: VideoReferenceMode = VideoReferenceMode.REFERENCE
    resolution: VideoResolution = VideoResolution.P720
    aspect_ratio: VideoAspectRatio = VideoAspectRatio.PORTRAIT_9_16
    duration_mode: VideoDurationMode = VideoDurationMode.FIXED
    fixed_duration: int | None = 5
    output_sound: bool = False
    reference_images: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def validate_video_task(self) -> "VideoBatchTaskCreate":
        self.prompt = self.prompt.strip()
        if not self.prompt:
            raise ValueError("提示词不能为空")
        if self.reference_mode == VideoReferenceMode.FIRST_FRAME:
            if len(self.reference_images) != 1:
                raise ValueError("首帧图模式必须上传且只能上传 1 张图片")
        if self.duration_mode == VideoDurationMode.FIXED:
            if self.fixed_duration not in {5, 10, 15}:
                raise ValueError("固定时长只能是 5、10 或 15 秒")
        else:
            self.fixed_duration = None
        return self


class VideoBatchCreate(BaseModel):
    tasks: list[VideoBatchTaskCreate] = Field(min_length=1, max_length=10)


class VideoBatchTaskCreated(BaseModel):
    client_index: int
    task_id: int


class VideoBatchCreated(BaseModel):
    batch_id: int
    status: BatchStatus
    tasks: list[VideoBatchTaskCreated]


class VideoTaskStatusResponse(BaseModel):
    id: int
    status: TaskStatus
    prompt: str
    reference_mode: VideoReferenceMode
    resolution: VideoResolution
    aspect_ratio: VideoAspectRatio
    duration_mode: VideoDurationMode
    fixed_duration: int | None
    output_sound: bool
    output_format: VideoOutputFormat
    error_code: str | None
    error_message: str | None
    results: list[GenerationResultResponse]


class VideoBatchStatusResponse(BaseModel):
    batch_id: int
    status: BatchStatus
    total_tasks: int
    success_tasks: int
    failed_tasks: int
    created_at: datetime
    updated_at: datetime
    tasks: list[VideoTaskStatusResponse]

