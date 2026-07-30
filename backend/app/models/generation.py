import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.image import ImageGenerationTaskDetail, TaskReferenceImage
    from app.models.provider_usage import ProviderUsage
    from app.models.result import GenerationResult
    from app.models.video import VideoGenerationTaskDetail


class GenerationType(str, enum.Enum):
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"


class BatchStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"


class TaskStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class GenerationBatch(Base):
    __tablename__ = "generation_batch"
    __table_args__ = {"comment": "生成批次主表：一次批量提交对应一条记录"}

    id: Mapped[int] = mapped_column(primary_key=True, comment="批次主键")
    batch_type: Mapped[GenerationType] = mapped_column(
        Enum(GenerationType), index=True, comment="批次类型：IMAGE图片，VIDEO视频"
    )
    status: Mapped[BatchStatus] = mapped_column(
        Enum(BatchStatus),
        default=BatchStatus.PENDING,
        index=True,
        comment="批次状态：PENDING/RUNNING/SUCCESS/PARTIAL_SUCCESS/FAILED",
    )
    total_tasks: Mapped[int] = mapped_column(
        Integer, default=0, comment="批次包含的任务总数"
    )
    success_tasks: Mapped[int] = mapped_column(
        Integer, default=0, comment="已成功任务数"
    )
    failed_tasks: Mapped[int] = mapped_column(
        Integer, default=0, comment="已失败任务数"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="批次创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        comment="批次最后更新时间",
    )
    tasks: Mapped[list["GenerationTask"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class GenerationTask(Base):
    __tablename__ = "generation_task"
    __table_args__ = {"comment": "生成任务主表：批次中的每张任务卡对应一条记录"}

    id: Mapped[int] = mapped_column(primary_key=True, comment="任务主键")
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("generation_batch.id"), index=True, comment="所属生成批次ID"
    )
    task_type: Mapped[GenerationType] = mapped_column(
        Enum(GenerationType), index=True, comment="任务类型：IMAGE图片，VIDEO视频"
    )
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus),
        default=TaskStatus.PENDING,
        index=True,
        comment="任务状态：PENDING/RUNNING/SUCCESS/FAILED",
    )
    prompt: Mapped[str] = mapped_column(Text, comment="用户提交的生成提示词")
    provider: Mapped[str | None] = mapped_column(
        String(64), comment="实际执行Provider，如mock/openai/volcengine_ark"
    )
    model: Mapped[str | None] = mapped_column(
        String(128), comment="实际调用的厂商模型ID"
    )
    provider_task_id: Mapped[str | None] = mapped_column(
        String(255), index=True, comment="厂商请求ID或异步任务ID，用于排障追踪"
    )
    error_code: Mapped[str | None] = mapped_column(
        String(64), comment="标准化失败错误码；成功时为空"
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, comment="失败原因摘要；成功时为空"
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="Worker开始执行时间"
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="任务成功或失败的结束时间"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="任务创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        comment="任务最后更新时间",
    )
    batch: Mapped[GenerationBatch] = relationship(back_populates="tasks")
    usage: Mapped["ProviderUsage | None"] = relationship(
        back_populates="task", cascade="all, delete-orphan", uselist=False
    )
    image_detail: Mapped["ImageGenerationTaskDetail | None"] = relationship(
        back_populates="task", cascade="all, delete-orphan", uselist=False
    )
    video_detail: Mapped["VideoGenerationTaskDetail | None"] = relationship(
        back_populates="task", cascade="all, delete-orphan", uselist=False
    )
    reference_images: Mapped[list["TaskReferenceImage"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by=(
            "TaskReferenceImage.position.is_(None), "
            "TaskReferenceImage.position, TaskReferenceImage.id"
        ),
    )
    results: Mapped[list["GenerationResult"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
