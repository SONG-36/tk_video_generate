from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.generation import GenerationBatch, GenerationTask


class VideoGenerationRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_task(
        self, task_id: int, *, for_update: bool = False
    ) -> GenerationTask | None:
        statement = (
            select(GenerationTask)
            .where(GenerationTask.id == task_id)
            .options(
                selectinload(GenerationTask.video_detail),
                selectinload(GenerationTask.reference_images),
                selectinload(GenerationTask.results),
                selectinload(GenerationTask.usage),
                selectinload(GenerationTask.batch).selectinload(
                    GenerationBatch.tasks
                ),
            )
        )
        if for_update:
            # 同一 Session 可能缓存旧 relationship；持锁追加必须以数据库最新状态覆盖缓存。
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        return self.session.scalar(statement)

    def get_batch(self, batch_id: int) -> GenerationBatch | None:
        statement = (
            select(GenerationBatch)
            .where(GenerationBatch.id == batch_id)
            .options(
                selectinload(GenerationBatch.tasks).selectinload(
                    GenerationTask.video_detail
                ),
                selectinload(GenerationBatch.tasks).selectinload(
                    GenerationTask.results
                ),
            )
        )
        return self.session.scalar(statement)
