"""add image generation workflow tables

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    aspect_ratio = sa.Enum(
        "PORTRAIT_9_16", "PORTRAIT_3_4", "SQUARE_1_1", name="imageaspectratio"
    )
    output_format = sa.Enum("PNG", name="imageoutputformat")
    result_type = sa.Enum("IMAGE", "VIDEO", name="resulttype")

    op.create_table(
        "image_generation_task_detail",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("generation_task.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("aspect_ratio", aspect_ratio, nullable=False),
        sa.Column("image_count", sa.Integer(), nullable=False),
        sa.Column("output_format", output_format, nullable=False),
        sa.UniqueConstraint("task_id"),
    )
    op.create_index(
        "ix_image_generation_task_detail_task_id",
        "image_generation_task_detail",
        ["task_id"],
    )
    op.create_table(
        "task_reference_image",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("generation_task.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_task_reference_image_task_id", "task_reference_image", ["task_id"])
    op.create_table(
        "generation_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("generation_task.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("result_type", result_type, nullable=False),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_generation_result_task_id", "generation_result", ["task_id"])
    op.create_index("ix_generation_result_result_type", "generation_result", ["result_type"])


def downgrade() -> None:
    op.drop_table("generation_result")
    op.drop_table("task_reference_image")
    op.drop_table("image_generation_task_detail")

