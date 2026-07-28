from decimal import Decimal

from sqlalchemy import Numeric

from app.core.database import Base
from app.models.generation import GenerationBatch, GenerationTask
from app.models.image import ImageGenerationTaskDetail, TaskReferenceImage
from app.models.provider_usage import ProviderUsage
from app.models.result import GenerationResult
from app.models.video import VideoGenerationTaskDetail


def test_models_registered() -> None:
    assert {
        "generation_batch",
        "generation_task",
        "image_generation_task_detail",
        "task_reference_image",
        "generation_result",
        "provider_usage",
        "video_generation_task_detail",
    } <= set(Base.metadata.tables)
    assert GenerationBatch.__tablename__ == "generation_batch"
    assert GenerationTask.__tablename__ == "generation_task"
    assert ImageGenerationTaskDetail.__tablename__ == "image_generation_task_detail"
    assert TaskReferenceImage.__tablename__ == "task_reference_image"
    assert GenerationResult.__tablename__ == "generation_result"
    assert VideoGenerationTaskDetail.__tablename__ == "video_generation_task_detail"


def test_business_tables_and_columns_have_comments() -> None:
    table_names = {
        "generation_batch",
        "generation_task",
        "image_generation_task_detail",
        "video_generation_task_detail",
        "task_reference_image",
        "generation_result",
        "provider_usage",
    }
    for table_name in table_names:
        table = Base.metadata.tables[table_name]
        assert table.comment
        assert all(column.comment for column in table.columns)


def test_money_columns_are_decimal() -> None:
    for name in ("billing_quantity", "unit_price", "original_amount", "exchange_rate", "amount_cny"):
        column_type = ProviderUsage.__table__.c[name].type
        assert isinstance(column_type, Numeric)
        assert column_type.asdecimal is True
        assert column_type.precision == 20
        assert column_type.scale == 8
    assert Decimal("0.1") + Decimal("0.2") == Decimal("0.3")
