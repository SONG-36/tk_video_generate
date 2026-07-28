"""initial generation schema"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    generation_type = sa.Enum("IMAGE", "VIDEO", name="generationtype")
    batch_status = sa.Enum(
        "PENDING", "RUNNING", "SUCCESS", "PARTIAL_SUCCESS", "FAILED", name="batchstatus"
    )
    task_status = sa.Enum("PENDING", "RUNNING", "SUCCESS", "FAILED", name="taskstatus")
    usage_source = sa.Enum(
        "PROVIDER", "LOCAL_CALCULATION", "UNKNOWN", name="usagesource"
    )
    op.create_table(
        "generation_batch",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_type", generation_type, nullable=False),
        sa.Column("status", batch_status, nullable=False),
        sa.Column("total_tasks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_tasks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_tasks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_generation_batch_batch_type", "generation_batch", ["batch_type"])
    op.create_index("ix_generation_batch_status", "generation_batch", ["status"])
    op.create_table(
        "generation_task",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("generation_batch.id"), nullable=False),
        sa.Column("task_type", generation_type, nullable=False),
        sa.Column("status", task_status, nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(64)),
        sa.Column("model", sa.String(128)),
        sa.Column("provider_task_id", sa.String(255)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_generation_task_batch_id", "generation_task", ["batch_id"])
    op.create_index("ix_generation_task_task_type", "generation_task", ["task_type"])
    op.create_index("ix_generation_task_status", "generation_task", ["status"])
    op.create_index("ix_generation_task_provider_task_id", "generation_task", ["provider_task_id"])
    op.create_table(
        "provider_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("generation_task.id"), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128)),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("total_tokens", sa.Integer()),
        sa.Column("billing_unit", sa.String(32)),
        sa.Column("billing_quantity", sa.Numeric(20, 8)),
        sa.Column("unit_price", sa.Numeric(20, 8)),
        sa.Column("original_currency", sa.String(8)),
        sa.Column("original_amount", sa.Numeric(20, 8)),
        sa.Column("exchange_rate", sa.Numeric(20, 8)),
        sa.Column("amount_cny", sa.Numeric(20, 8)),
        sa.Column("usage_source", usage_source, nullable=False),
        sa.Column("pricing_snapshot", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("task_id"),
    )
    op.create_index("ix_provider_usage_task_id", "provider_usage", ["task_id"])


def downgrade() -> None:
    op.drop_table("provider_usage")
    op.drop_table("generation_task")
    op.drop_table("generation_batch")

