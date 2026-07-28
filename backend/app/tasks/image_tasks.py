import asyncio
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session, sessionmaker

from app.core.database import SessionLocal
from app.providers.image.base import ImageGenerationProvider
from app.providers.image.factory import create_image_provider
from app.services.file_storage import FileStorageService
from app.services.image_generation import ImageGenerationService
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def run_image_generation_task(
    task_id: int,
    session_factory: sessionmaker[Session] = SessionLocal,
    provider_factory: Callable[[], ImageGenerationProvider] = create_image_provider,
    storage: FileStorageService | None = None,
) -> dict[str, object]:
    return asyncio.run(
        _run_image_generation_task_async(
            task_id,
            session_factory=session_factory,
            provider_factory=provider_factory,
            storage=storage,
        )
    )


async def _run_image_generation_task_async(
    task_id: int,
    session_factory: sessionmaker[Session],
    provider_factory: Callable[[], ImageGenerationProvider],
    storage: FileStorageService | None,
) -> dict[str, object]:
    session = session_factory()
    provider: ImageGenerationProvider | None = None
    try:
        provider = provider_factory()
        logger.info("Starting image generation task_id=%s", task_id)
        task = await ImageGenerationService(provider, storage=storage).execute(
            session, task_id
        )
        logger.info("Completed image generation task_id=%s", task_id)
        return {
            "task_id": task_id,
            "status": task.status.value,
            "result_count": len(task.results),
        }
    except Exception as exc:
        session.rollback()
        ImageGenerationService.mark_failed(session, task_id, exc)
        logger.exception("Image generation failed task_id=%s", task_id)
        return {"task_id": task_id, "status": "FAILED", "error": str(exc)}
    finally:
        try:
            close = getattr(provider, "close", None) if provider is not None else None
            if close is not None:
                await close()
        except Exception as exc:
            logger.exception(
                "Image provider cleanup failed task_id=%s stage=close "
                "provider=%s model=%s exception_type=%s exception_repr=%r",
                task_id,
                getattr(provider, "name", None),
                getattr(provider, "model", None),
                type(exc).__name__,
                exc,
            )
        finally:
            try:
                session.close()
            except Exception as exc:
                logger.exception(
                    "Image database session cleanup failed task_id=%s "
                    "stage=session_close exception_type=%s exception_repr=%r",
                    task_id,
                    type(exc).__name__,
                    exc,
                )


@celery_app.task(name="app.tasks.image_tasks.generate_image")
def generate_image_task(task_id: int) -> dict[str, object]:
    return run_image_generation_task(task_id)
