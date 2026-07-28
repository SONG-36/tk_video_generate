import asyncio
import logging
import re
from collections.abc import Callable

from sqlalchemy.orm import Session, sessionmaker

from app.core.database import SessionLocal
from app.providers.video.base import VideoGenerationProvider
from app.providers.video.factory import create_video_provider
from app.services.file_storage import FileStorageService
from app.services.video_generation import VideoGenerationService
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _safe_exception_repr(exc: Exception) -> str:
    value = repr(exc)
    value = re.sub(r"https?://[^\s'\"\)]+", "<redacted-url>", value)
    value = re.sub(
        r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+",
        "Bearer <redacted>",
        value,
    )
    return value[:500]


def run_video_generation_task(
    task_id: int,
    session_factory: sessionmaker[Session] = SessionLocal,
    provider_factory: Callable[[], VideoGenerationProvider] = create_video_provider,
    storage: FileStorageService | None = None,
) -> dict[str, object]:
    return asyncio.run(
        _run_video_generation_task_async(
            task_id,
            session_factory=session_factory,
            provider_factory=provider_factory,
            storage=storage,
        )
    )


async def _run_video_generation_task_async(
    task_id: int,
    session_factory: sessionmaker[Session],
    provider_factory: Callable[[], VideoGenerationProvider],
    storage: FileStorageService | None,
) -> dict[str, object]:
    session = session_factory()
    provider: VideoGenerationProvider | None = None
    try:
        provider = provider_factory()
        logger.info("Starting video generation task_id=%s", task_id)
        task = await VideoGenerationService(provider, storage=storage).execute(
            session, task_id
        )
        logger.info("Completed video generation task_id=%s", task_id)
        return {
            "task_id": task_id,
            "status": task.status.value,
            "result_count": len(task.results),
        }
    except Exception as exc:
        session.rollback()
        VideoGenerationService.mark_failed(
            session,
            task_id,
            exc,
            provider=getattr(provider, "name", None),
            model=getattr(provider, "model", None),
            provider_task_id=getattr(provider, "last_provider_task_id", None),
        )
        logger.error(
            "Video generation business failure task_id=%s provider_task_id=%s "
            "stage=execute aspect_ratio=%s exception_type=%s exception_repr=%s; "
            "returning FAILED result for existing Celery semantics",
            task_id,
            getattr(provider, "last_provider_task_id", None),
            getattr(provider, "last_aspect_ratio", None),
            type(exc).__name__,
            _safe_exception_repr(exc),
        )
        return {"task_id": task_id, "status": "FAILED", "error": str(exc)}
    finally:
        close = getattr(provider, "close", None) if provider is not None else None
        if close is not None:
            try:
                await close()
            except Exception as exc:
                logger.error(
                    "Video provider cleanup failed task_id=%s provider_task_id=%s "
                    "stage=close aspect_ratio=%s exception_type=%s "
                    "exception_repr=%s",
                    task_id,
                    getattr(provider, "last_provider_task_id", None),
                    getattr(provider, "last_aspect_ratio", None),
                    type(exc).__name__,
                    _safe_exception_repr(exc),
                )
        session.close()


@celery_app.task(name="app.tasks.video_tasks.generate_video")
def generate_video_task(task_id: int) -> dict[str, object]:
    return run_video_generation_task(task_id)
