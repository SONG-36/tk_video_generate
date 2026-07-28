from celery import Celery

from app.core.config import get_settings
from app.core.logging import configure_http_client_logging


configure_http_client_logging()
settings = get_settings()
celery_app = Celery("tiktok_operations", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_routes={
        "app.tasks.mock.generate_image_mock": {"queue": "image"},
        "app.tasks.mock.generate_video_mock": {"queue": "video"},
        "app.tasks.image_tasks.generate_image": {"queue": "image"},
        "app.tasks.video_tasks.generate_video": {"queue": "video"},
    },
    imports=("app.tasks.mock", "app.tasks.image_tasks", "app.tasks.video_tasks"),
)
