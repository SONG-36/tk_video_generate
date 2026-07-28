import json

from app.main import app
from app.providers.video.mock import MockVideoGenerationProvider
from app.tasks.video_tasks import run_video_generation_task
from tests.test_video_api import create_video_test_client


def test_video_status_polling_and_download(workspace_tmp_path, monkeypatch) -> None:
    client, sessions, _, storage = create_video_test_client(
        workspace_tmp_path, monkeypatch
    )
    payload = {
        "tasks": [
            {
                "prompt": "download video",
                "reference_mode": "REFERENCE",
                "resolution": "720P",
                "aspect_ratio": "16:9",
                "duration_mode": "SMART",
                "reference_images": [],
            }
        ]
    }
    with client:
        created = client.post(
            "/api/video/batches",
            files={"payload": (None, json.dumps(payload), "application/json")},
        ).json()
        task_id = created["tasks"][0]["task_id"]
        run_video_generation_task(
            task_id,
            session_factory=sessions,
            provider_factory=MockVideoGenerationProvider,
            storage=storage,
        )
        status = client.get(f"/api/video/batches/{created['batch_id']}/status")
        result_id = status.json()["tasks"][0]["results"][0]["id"]
        download = client.get(f"/api/files/download/{result_id}")
        preview = client.get(f"/api/files/download/{result_id}?inline=true")
    app.dependency_overrides.clear()

    assert status.status_code == 200
    assert status.json()["status"] == "SUCCESS"
    assert status.json()["tasks"][0]["output_format"] == "MP4"
    assert download.status_code == 200
    assert download.headers["content-type"] == "video/mp4"
    assert download.content[4:8] == b"ftyp"
    assert "attachment" in download.headers["content-disposition"]
    assert "inline" in preview.headers["content-disposition"]
