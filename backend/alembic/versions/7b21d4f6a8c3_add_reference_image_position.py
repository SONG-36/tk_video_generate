"""add reference image position

Revision ID: 7b21d4f6a8c3
Revises: e943f58030e3
Create Date: 2026-07-30 16:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7b21d4f6a8c3"
down_revision: Union[str, None] = "e943f58030e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "task_reference_image",
        sa.Column(
            "position",
            sa.Integer(),
            nullable=True,
            comment="参考图顺序（从0开始）；历史数据为空时按主键排序",
        ),
    )
    op.create_index(
        "ix_task_reference_image_task_position",
        "task_reference_image",
        ["task_id", "position", "id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_task_reference_image_task_position",
        "task_reference_image",
        ["task_id", "position"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_task_reference_image_task_position",
        "task_reference_image",
        type_="unique",
    )
    op.drop_index(
        "ix_task_reference_image_task_position",
        table_name="task_reference_image",
    )
    op.drop_column("task_reference_image", "position")
