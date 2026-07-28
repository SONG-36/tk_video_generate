import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.generation import GenerationTask


class ResultType(str, enum.Enum):
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"


class GenerationResult(Base):
    __tablename__ = "generation_result"
    __table_args__ = {
        "comment": "生成结果文件表：一条记录对应一个文件，任务重跑时替换旧结果"
    }

    id: Mapped[int] = mapped_column(primary_key=True, comment="生成结果主键")
    task_id: Mapped[int] = mapped_column(
        ForeignKey("generation_task.id", ondelete="CASCADE"),
        index=True,
        comment="所属生成任务ID",
    )
    result_type: Mapped[ResultType] = mapped_column(
        Enum(ResultType), index=True, comment="结果类型：IMAGE图片，VIDEO视频"
    )
    file_path: Mapped[str] = mapped_column(
        String(512), comment="相对STORAGE_ROOT的结果文件路径"
    )
    file_name: Mapped[str] = mapped_column(String(255), comment="下载时使用的文件名")
    file_size: Mapped[int] = mapped_column(Integer, comment="结果文件大小，单位字节")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="结果保存时间"
    )
    task: Mapped["GenerationTask"] = relationship(back_populates="results")
