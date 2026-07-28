import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.generation import GenerationTask


class UsageSource(str, enum.Enum):
    PROVIDER = "PROVIDER"
    LOCAL_CALCULATION = "LOCAL_CALCULATION"
    UNKNOWN = "UNKNOWN"


class ProviderUsage(Base):
    __tablename__ = "provider_usage"
    __table_args__ = {"comment": "厂商用量与费用表：与generation_task一对一"}

    id: Mapped[int] = mapped_column(primary_key=True, comment="用量记录主键")
    task_id: Mapped[int] = mapped_column(
        ForeignKey("generation_task.id"),
        unique=True,
        index=True,
        comment="关联的生成任务ID，唯一",
    )
    provider: Mapped[str] = mapped_column(
        String(64), comment="实际调用的Provider名称"
    )
    model: Mapped[str | None] = mapped_column(
        String(128), comment="实际调用的厂商模型ID"
    )
    input_tokens: Mapped[int | None] = mapped_column(
        Integer, comment="厂商返回的输入Token数；未提供时为空"
    )
    output_tokens: Mapped[int | None] = mapped_column(
        Integer, comment="厂商返回的输出Token数；未提供时为空"
    )
    total_tokens: Mapped[int | None] = mapped_column(
        Integer, comment="厂商返回的总Token数；未提供时为空"
    )
    billing_unit: Mapped[str | None] = mapped_column(
        String(32), comment="计费单位，如token、image或second"
    )
    billing_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8), comment="按计费单位统计的用量"
    )
    unit_price: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8), comment="调用时采用的单位价格"
    )
    original_currency: Mapped[str | None] = mapped_column(
        String(8), comment="厂商原始计费币种，如USD或CNY"
    )
    original_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8), comment="厂商币种下的原始金额"
    )
    exchange_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8), comment="原始币种换算人民币的汇率"
    )
    amount_cny: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8), comment="折算后的人民币金额"
    )
    usage_source: Mapped[UsageSource] = mapped_column(
        Enum(UsageSource),
        default=UsageSource.UNKNOWN,
        comment="用量来源：PROVIDER/LOCAL_CALCULATION/UNKNOWN",
    )
    pricing_snapshot: Mapped[dict | None] = mapped_column(
        JSON, comment="费用计算采用的价格与规则快照JSON"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="用量记录创建时间"
    )
    task: Mapped["GenerationTask"] = relationship(back_populates="usage")
