import asyncio
import logging

from app.models.image import ImageAspectRatio, ImageOutputFormat
from app.providers.image.base import ImageGenerationRequest
from app.providers.image.mock import MockImageGenerationProvider
from app.providers.video.mock import MockVideoGenerationProvider
from app.services.generation import VideoGenerationService
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.mock.generate_image_mock")
def generate_image_mock(task_id: int) -> dict[str, object]:
    logger.info("Running mock image task task_id=%s", task_id)
    result = asyncio.run(
        MockImageGenerationProvider().generate(
            ImageGenerationRequest(
                task_id=task_id,
                prompt="mock image prompt",
                aspect_ratio=ImageAspectRatio.PORTRAIT_9_16,
                image_count=1,
                output_format=ImageOutputFormat.PNG,
                reference_paths=[],
            )
        )
    )
    return {"task_id": task_id, "status": "success", "outputs": len(result.images)}


@celery_app.task(name="app.tasks.mock.generate_video_mock")
def generate_video_mock(task_id: int) -> dict[str, object]:
    logger.info("Running mock video task task_id=%s", task_id)
    result = asyncio.run(
        VideoGenerationService(MockVideoGenerationProvider()).run_mock(task_id)
    )
    return {
        "task_id": task_id,
        "status": "success",
        "output_size": len(result.content),
    }
