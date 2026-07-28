"""add Chinese table and column comments

Revision ID: 0004
Revises: 0003
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NO_DEFAULT = object()

TABLE_COMMENTS = {
    "generation_batch": "生成批次主表：一次批量提交对应一条记录",
    "generation_task": "生成任务主表：批次中的每张任务卡对应一条记录",
    "image_generation_task_detail": "图片任务参数表：与generation_task一对一",
    "video_generation_task_detail": "视频任务参数表：与generation_task一对一",
    "task_reference_image": "任务参考图片表：图片任务与视频任务共用，一张图片一条记录",
    "generation_result": "生成结果文件表：一条记录对应一个文件，任务重跑时替换旧结果",
    "provider_usage": "厂商用量与费用表：与generation_task一对一",
}


def _column_specs() -> dict[str, list[tuple]]:
    generation_type = sa.Enum("IMAGE", "VIDEO", name="generationtype")
    batch_status = sa.Enum(
        "PENDING",
        "RUNNING",
        "SUCCESS",
        "PARTIAL_SUCCESS",
        "FAILED",
        name="batchstatus",
    )
    task_status = sa.Enum(
        "PENDING", "RUNNING", "SUCCESS", "FAILED", name="taskstatus"
    )
    image_aspect_ratio = sa.Enum(
        "PORTRAIT_9_16", "PORTRAIT_3_4", "SQUARE_1_1", name="imageaspectratio"
    )
    image_output_format = sa.Enum("PNG", name="imageoutputformat")
    result_type = sa.Enum("IMAGE", "VIDEO", name="resulttype")
    video_reference_mode = sa.Enum(
        "REFERENCE", "FIRST_FRAME", name="videoreferencemode"
    )
    video_resolution = sa.Enum("P480", "P720", name="videoresolution")
    video_aspect_ratio = sa.Enum(
        "LANDSCAPE_16_9", "PORTRAIT_9_16", name="videoaspectratio"
    )
    video_duration_mode = sa.Enum("FIXED", "SMART", name="videodurationmode")
    video_output_format = sa.Enum("MP4", name="videooutputformat")
    usage_source = sa.Enum(
        "PROVIDER", "LOCAL_CALCULATION", "UNKNOWN", name="usagesource"
    )
    timestamp_default = sa.text("CURRENT_TIMESTAMP")

    # tuple: name, type, nullable, comment, server_default, autoincrement
    return {
        "generation_batch": [
            ("id", sa.Integer(), False, "批次主键", _NO_DEFAULT, True),
            (
                "batch_type",
                generation_type,
                False,
                "批次类型：IMAGE图片，VIDEO视频",
                _NO_DEFAULT,
                False,
            ),
            (
                "status",
                batch_status,
                False,
                "批次状态：PENDING/RUNNING/SUCCESS/PARTIAL_SUCCESS/FAILED",
                _NO_DEFAULT,
                False,
            ),
            ("total_tasks", sa.Integer(), False, "批次包含的任务总数", sa.text("0"), False),
            ("success_tasks", sa.Integer(), False, "已成功任务数", sa.text("0"), False),
            ("failed_tasks", sa.Integer(), False, "已失败任务数", sa.text("0"), False),
            ("created_at", sa.DateTime(), False, "批次创建时间", timestamp_default, False),
            (
                "updated_at",
                sa.DateTime(),
                False,
                "批次最后更新时间",
                timestamp_default,
                False,
            ),
        ],
        "generation_task": [
            ("id", sa.Integer(), False, "任务主键", _NO_DEFAULT, True),
            ("batch_id", sa.Integer(), False, "所属生成批次ID", _NO_DEFAULT, False),
            (
                "task_type",
                generation_type,
                False,
                "任务类型：IMAGE图片，VIDEO视频",
                _NO_DEFAULT,
                False,
            ),
            (
                "status",
                task_status,
                False,
                "任务状态：PENDING/RUNNING/SUCCESS/FAILED",
                _NO_DEFAULT,
                False,
            ),
            ("prompt", sa.Text(), False, "用户提交的生成提示词", _NO_DEFAULT, False),
            (
                "provider",
                sa.String(64),
                True,
                "实际执行Provider，如mock/openai/volcengine_ark",
                _NO_DEFAULT,
                False,
            ),
            ("model", sa.String(128), True, "实际调用的厂商模型ID", _NO_DEFAULT, False),
            (
                "provider_task_id",
                sa.String(255),
                True,
                "厂商请求ID或异步任务ID，用于排障追踪",
                _NO_DEFAULT,
                False,
            ),
            (
                "error_code",
                sa.String(64),
                True,
                "标准化失败错误码；成功时为空",
                _NO_DEFAULT,
                False,
            ),
            (
                "error_message",
                sa.Text(),
                True,
                "失败原因摘要；成功时为空",
                _NO_DEFAULT,
                False,
            ),
            ("started_at", sa.DateTime(), True, "Worker开始执行时间", _NO_DEFAULT, False),
            (
                "finished_at",
                sa.DateTime(),
                True,
                "任务成功或失败的结束时间",
                _NO_DEFAULT,
                False,
            ),
            ("created_at", sa.DateTime(), False, "任务创建时间", timestamp_default, False),
            (
                "updated_at",
                sa.DateTime(),
                False,
                "任务最后更新时间",
                timestamp_default,
                False,
            ),
        ],
        "image_generation_task_detail": [
            ("id", sa.Integer(), False, "图片任务参数主键", _NO_DEFAULT, True),
            (
                "task_id",
                sa.Integer(),
                False,
                "关联的图片生成任务ID，唯一",
                _NO_DEFAULT,
                False,
            ),
            (
                "aspect_ratio",
                image_aspect_ratio,
                False,
                "图片比例：9:16、3:4、1:1",
                _NO_DEFAULT,
                False,
            ),
            ("image_count", sa.Integer(), False, "本任务生成图片数量：1、2或4", _NO_DEFAULT, False),
            (
                "output_format",
                image_output_format,
                False,
                "输出格式，当前固定为PNG",
                _NO_DEFAULT,
                False,
            ),
        ],
        "video_generation_task_detail": [
            ("id", sa.Integer(), False, "视频任务参数主键", _NO_DEFAULT, True),
            (
                "task_id",
                sa.Integer(),
                False,
                "关联的视频生成任务ID，唯一",
                _NO_DEFAULT,
                False,
            ),
            (
                "reference_mode",
                video_reference_mode,
                False,
                "参考模式：REFERENCE参考生成，FIRST_FRAME首帧图",
                _NO_DEFAULT,
                False,
            ),
            (
                "resolution",
                video_resolution,
                False,
                "输出分辨率：480P或720P",
                _NO_DEFAULT,
                False,
            ),
            (
                "aspect_ratio",
                video_aspect_ratio,
                False,
                "视频比例：16:9或9:16",
                _NO_DEFAULT,
                False,
            ),
            (
                "duration_mode",
                video_duration_mode,
                False,
                "时长模式：FIXED固定，SMART智能",
                _NO_DEFAULT,
                False,
            ),
            (
                "fixed_duration",
                sa.Integer(),
                True,
                "固定时长秒数：5、10或15；智能时长时为空",
                _NO_DEFAULT,
                False,
            ),
            (
                "output_sound",
                sa.Boolean(),
                False,
                "是否要求生成同步声音",
                sa.false(),
                False,
            ),
            (
                "output_format",
                video_output_format,
                False,
                "输出格式，当前固定为MP4",
                _NO_DEFAULT,
                False,
            ),
        ],
        "task_reference_image": [
            ("id", sa.Integer(), False, "参考图片主键", _NO_DEFAULT, True),
            ("task_id", sa.Integer(), False, "所属生成任务ID", _NO_DEFAULT, False),
            (
                "file_path",
                sa.String(512),
                False,
                "相对STORAGE_ROOT的文件路径",
                _NO_DEFAULT,
                False,
            ),
            (
                "file_name",
                sa.String(255),
                False,
                "用户上传时的原始文件名",
                _NO_DEFAULT,
                False,
            ),
            ("file_size", sa.Integer(), False, "文件大小，单位字节", _NO_DEFAULT, False),
            (
                "mime_type",
                sa.String(64),
                False,
                "校验后的MIME类型，如image/png",
                _NO_DEFAULT,
                False,
            ),
            ("created_at", sa.DateTime(), False, "上传记录创建时间", timestamp_default, False),
        ],
        "generation_result": [
            ("id", sa.Integer(), False, "生成结果主键", _NO_DEFAULT, True),
            ("task_id", sa.Integer(), False, "所属生成任务ID", _NO_DEFAULT, False),
            (
                "result_type",
                result_type,
                False,
                "结果类型：IMAGE图片，VIDEO视频",
                _NO_DEFAULT,
                False,
            ),
            (
                "file_path",
                sa.String(512),
                False,
                "相对STORAGE_ROOT的结果文件路径",
                _NO_DEFAULT,
                False,
            ),
            (
                "file_name",
                sa.String(255),
                False,
                "下载时使用的文件名",
                _NO_DEFAULT,
                False,
            ),
            ("file_size", sa.Integer(), False, "结果文件大小，单位字节", _NO_DEFAULT, False),
            ("created_at", sa.DateTime(), False, "结果保存时间", timestamp_default, False),
        ],
        "provider_usage": [
            ("id", sa.Integer(), False, "用量记录主键", _NO_DEFAULT, True),
            (
                "task_id",
                sa.Integer(),
                False,
                "关联的生成任务ID，唯一",
                _NO_DEFAULT,
                False,
            ),
            (
                "provider",
                sa.String(64),
                False,
                "实际调用的Provider名称",
                _NO_DEFAULT,
                False,
            ),
            ("model", sa.String(128), True, "实际调用的厂商模型ID", _NO_DEFAULT, False),
            (
                "input_tokens",
                sa.Integer(),
                True,
                "厂商返回的输入Token数；未提供时为空",
                _NO_DEFAULT,
                False,
            ),
            (
                "output_tokens",
                sa.Integer(),
                True,
                "厂商返回的输出Token数；未提供时为空",
                _NO_DEFAULT,
                False,
            ),
            (
                "total_tokens",
                sa.Integer(),
                True,
                "厂商返回的总Token数；未提供时为空",
                _NO_DEFAULT,
                False,
            ),
            (
                "billing_unit",
                sa.String(32),
                True,
                "计费单位，如token、image或second",
                _NO_DEFAULT,
                False,
            ),
            (
                "billing_quantity",
                sa.Numeric(20, 8),
                True,
                "按计费单位统计的用量",
                _NO_DEFAULT,
                False,
            ),
            (
                "unit_price",
                sa.Numeric(20, 8),
                True,
                "调用时采用的单位价格",
                _NO_DEFAULT,
                False,
            ),
            (
                "original_currency",
                sa.String(8),
                True,
                "厂商原始计费币种，如USD或CNY",
                _NO_DEFAULT,
                False,
            ),
            (
                "original_amount",
                sa.Numeric(20, 8),
                True,
                "厂商币种下的原始金额",
                _NO_DEFAULT,
                False,
            ),
            (
                "exchange_rate",
                sa.Numeric(20, 8),
                True,
                "原始币种换算人民币的汇率",
                _NO_DEFAULT,
                False,
            ),
            (
                "amount_cny",
                sa.Numeric(20, 8),
                True,
                "折算后的人民币金额",
                _NO_DEFAULT,
                False,
            ),
            (
                "usage_source",
                usage_source,
                False,
                "用量来源：PROVIDER/LOCAL_CALCULATION/UNKNOWN",
                _NO_DEFAULT,
                False,
            ),
            (
                "pricing_snapshot",
                sa.JSON(),
                True,
                "费用计算采用的价格与规则快照JSON",
                _NO_DEFAULT,
                False,
            ),
            (
                "created_at",
                sa.DateTime(),
                False,
                "用量记录创建时间",
                timestamp_default,
                False,
            ),
        ],
    }


def _apply_column_comments(add: bool) -> None:
    for table_name, columns in _column_specs().items():
        for (
            column_name,
            existing_type,
            existing_nullable,
            column_comment,
            existing_server_default,
            existing_autoincrement,
        ) in columns:
            kwargs = {
                "existing_type": existing_type,
                "existing_nullable": existing_nullable,
                "existing_autoincrement": existing_autoincrement,
            }
            if existing_server_default is not _NO_DEFAULT:
                kwargs["existing_server_default"] = existing_server_default
            if add:
                kwargs["comment"] = column_comment
            else:
                kwargs["comment"] = None
                kwargs["existing_comment"] = column_comment
            op.alter_column(table_name, column_name, **kwargs)


def upgrade() -> None:
    for table_name, table_comment in TABLE_COMMENTS.items():
        op.create_table_comment(table_name, table_comment)
    _apply_column_comments(add=True)


def downgrade() -> None:
    _apply_column_comments(add=False)
    for table_name, table_comment in reversed(TABLE_COMMENTS.items()):
        op.drop_table_comment(table_name, existing_comment=table_comment)
