"""add video generation workflow table

Revision ID: 0003
Revises: 0002
"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    reference_mode = sa.Enum("REFERENCE", "FIRST_FRAME", name="videoreferencemode")
    resolution = sa.Enum("P480", "P720", name="videoresolution")
    aspect_ratio = sa.Enum(
        "LANDSCAPE_16_9", "PORTRAIT_9_16", name="videoaspectratio"
    )
    duration_mode = sa.Enum("FIXED", "SMART", name="videodurationmode")
    output_format = sa.Enum("MP4", name="videooutputformat")
    op.create_table(
        "video_generation_task_detail",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("generation_task.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reference_mode", reference_mode, nullable=False),
        sa.Column("resolution", resolution, nullable=False),
        sa.Column("aspect_ratio", aspect_ratio, nullable=False),
        sa.Column("duration_mode", duration_mode, nullable=False),
        sa.Column("fixed_duration", sa.Integer()),
        sa.Column("output_sound", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("output_format", output_format, nullable=False),
        sa.UniqueConstraint("task_id"),
    )
    op.create_index(
        "ix_video_generation_task_detail_task_id",
        "video_generation_task_detail",
        ["task_id"],
    )


def downgrade() -> None:
    op.drop_table("video_generation_task_detail")

