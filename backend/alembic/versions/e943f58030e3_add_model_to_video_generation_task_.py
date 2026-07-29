"""add_model_to_video_generation_task_detail

Revision ID: e943f58030e3
Revises: 0004
Create Date: 2026-07-29 14:54:41.967746
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "e943f58030e3"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    video_model_enum = sa.Enum(
        "SEEDANCE_2_0",
        "SEEDANCE_2_0_MINI",
        name="videomodel",
    )

    # 先使用临时数据库默认值添加非空字段，
    # 让表中已有的视频任务能够顺利完成迁移。
    op.add_column(
        "video_generation_task_detail",
        sa.Column(
            "model",
            video_model_enum,
            nullable=False,
            server_default="SEEDANCE_2_0_MINI",
            comment="用户选择的视频模型ID",
        ),
    )

    # 数据迁移完成后删除数据库层默认值。
    # 后续新任务的默认模型仍由 SQLAlchemy/Python 代码决定。
    op.alter_column(
        "video_generation_task_detail",
        "model",
        existing_type=video_model_enum,
        existing_nullable=False,
        server_default=None,
        existing_comment="用户选择的视频模型ID",
    )

    # 同步固定时长字段的数据库注释。
    op.alter_column(
        "video_generation_task_detail",
        "fixed_duration",
        existing_type=mysql.INTEGER(),
        comment="固定时长秒数：4～15；智能时长时为空",
        existing_comment="固定时长秒数：5、10或15；智能时长时为空",
        existing_nullable=True,
    )


def downgrade() -> None:
    # 恢复固定时长字段的旧注释。
    op.alter_column(
        "video_generation_task_detail",
        "fixed_duration",
        existing_type=mysql.INTEGER(),
        comment="固定时长秒数：5、10或15；智能时长时为空",
        existing_comment="固定时长秒数：4～15；智能时长时为空",
        existing_nullable=True,
    )

    # 删除本次新增的视频模型字段。
    op.drop_column(
        "video_generation_task_detail",
        "model",
    )