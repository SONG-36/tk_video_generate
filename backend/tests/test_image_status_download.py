import json

from app.main import app
from app.providers.image.mock import MockImageGenerationProvider
from app.tasks.image_tasks import run_image_generation_task
from tests.test_image_api import create_test_client


def test_status_polling_and_single_result_download(workspace_tmp_path, monkeypatch) -> None:
    client, sessions, _, storage = create_test_client(workspace_tmp_path, monkeypatch)
    payload = {
        "tasks": [
            {
                "prompt": "download test",
                "aspect_ratio": "1:1",
                "image_count": 2,
                "reference_images": [],
            }
        ]
    }
    with client:
        created = client.post(
            "/api/image/batches",
            files={"payload": (None, json.dumps(payload), "application/json")},
        ).json()
        task_id = created["tasks"][0]["task_id"]
        run_image_generation_task(
            task_id,
            session_factory=sessions,
            provider_factory=MockImageGenerationProvider,
            storage=storage,
        )
        status = client.get(
            f"/api/image/batches/{created['batch_id']}/status"
        )
        result_id = status.json()["tasks"][0]["results"][0]["id"]
        download = client.get(f"/api/files/download/{result_id}")
        preview = client.get(f"/api/files/download/{result_id}?inline=true")
    app.dependency_overrides.clear()

    assert status.status_code == 200
    assert status.json()["status"] == "SUCCESS"
    assert len(status.json()["tasks"][0]["results"]) == 2
    assert download.status_code == 200
    assert download.headers["content-type"] == "image/png"
    assert "attachment" in download.headers["content-disposition"]
    assert "inline" in preview.headers["content-disposition"]

