from app.tasks.celery_app import celery_app
from app.tasks.mock import generate_image_mock, generate_video_mock


def test_mock_tasks_eager_execution() -> None:
    celery_app.conf.task_always_eager = True
    image_result = generate_image_mock.delay(11).get()
    video_result = generate_video_mock.delay(12).get()
    assert image_result["status"] == "success"
    assert image_result["task_id"] == 11
    assert video_result["status"] == "success"
    assert video_result["task_id"] == 12

