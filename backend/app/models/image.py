import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.generation import GenerationTask


class ImageAspectRatio(str, enum.Enum):
    PORTRAIT_9_16 = "9:16"
    PORTRAIT_3_4 = "3:4"
    SQUARE_1_1 = "1:1"


class ImageOutputFormat(str, enum.Enum):
    PNG = "PNG"


class ImageGenerationTaskDetail(Base):
    __tablename__ = "image_generation_task_detail"
    __table_args__ = (
        UniqueConstraint("task_id"),
        {"comment": "图片任务参数表：与generation_task一对一"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="图片任务参数主键")
    task_id: Mapped[int] = mapped_column(
        ForeignKey("generation_task.id", ondelete="CASCADE"),
        index=True,
        comment="关联的图片生成任务ID，唯一",
    )
    aspect_ratio: Mapped[ImageAspectRatio] = mapped_column(
        Enum(ImageAspectRatio), comment="图片比例：9:16、3:4、1:1"
    )
    image_count: Mapped[int] = mapped_column(
        Integer, comment="本任务生成图片数量：1、2或4"
    )
    output_format: Mapped[ImageOutputFormat] = mapped_column(
        Enum(ImageOutputFormat),
        default=ImageOutputFormat.PNG,
        comment="输出格式，当前固定为PNG",
    )
    task: Mapped["GenerationTask"] = relationship(back_populates="image_detail")


class TaskReferenceImage(Base):
    __tablename__ = "task_reference_image"
    __table_args__ = {"comment": "任务参考图片表：图片任务与视频任务共用，一张图片一条记录"}

    id: Mapped[int] = mapped_column(primary_key=True, comment="参考图片主键")
    task_id: Mapped[int] = mapped_column(
        ForeignKey("generation_task.id", ondelete="CASCADE"),
        index=True,
        comment="所属生成任务ID",
    )
    file_path: Mapped[str] = mapped_column(
        String(512), comment="相对STORAGE_ROOT的文件路径"
    )
    file_name: Mapped[str] = mapped_column(
        String(255), comment="用户上传时的原始文件名"
    )
    file_size: Mapped[int] = mapped_column(Integer, comment="文件大小，单位字节")
    mime_type: Mapped[str] = mapped_column(
        String(64), comment="校验后的MIME类型，如image/png"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="上传记录创建时间"
    )
    task: Mapped["GenerationTask"] = relationship(back_populates="reference_images")
