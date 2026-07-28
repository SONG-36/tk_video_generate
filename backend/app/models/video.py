import enum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.generation import GenerationTask


class VideoReferenceMode(str, enum.Enum):
    REFERENCE = "REFERENCE"
    FIRST_FRAME = "FIRST_FRAME"


class VideoResolution(str, enum.Enum):
    P480 = "480P"
    P720 = "720P"


class VideoAspectRatio(str, enum.Enum):
    LANDSCAPE_16_9 = "16:9"
    PORTRAIT_9_16 = "9:16"


class VideoDurationMode(str, enum.Enum):
    FIXED = "FIXED"
    SMART = "SMART"


class VideoOutputFormat(str, enum.Enum):
    MP4 = "MP4"


class VideoGenerationTaskDetail(Base):
    __tablename__ = "video_generation_task_detail"
    __table_args__ = (
        UniqueConstraint("task_id"),
        {"comment": "视频任务参数表：与generation_task一对一"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="视频任务参数主键")
    task_id: Mapped[int] = mapped_column(
        ForeignKey("generation_task.id", ondelete="CASCADE"),
        index=True,
        comment="关联的视频生成任务ID，唯一",
    )
    reference_mode: Mapped[VideoReferenceMode] = mapped_column(
        Enum(VideoReferenceMode),
        comment="参考模式：REFERENCE参考生成，FIRST_FRAME首帧图",
    )
    resolution: Mapped[VideoResolution] = mapped_column(
        Enum(VideoResolution), comment="输出分辨率：480P或720P"
    )
    aspect_ratio: Mapped[VideoAspectRatio] = mapped_column(
        Enum(VideoAspectRatio), comment="视频比例：16:9或9:16"
    )
    duration_mode: Mapped[VideoDurationMode] = mapped_column(
        Enum(VideoDurationMode), comment="时长模式：FIXED固定，SMART智能"
    )
    fixed_duration: Mapped[int | None] = mapped_column(
        Integer, comment="固定时长秒数：5、10或15；智能时长时为空"
    )
    output_sound: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否要求生成同步声音"
    )
    output_format: Mapped[VideoOutputFormat] = mapped_column(
        Enum(VideoOutputFormat),
        default=VideoOutputFormat.MP4,
        comment="输出格式，当前固定为MP4",
    )
    task: Mapped["GenerationTask"] = relationship(back_populates="video_detail")
