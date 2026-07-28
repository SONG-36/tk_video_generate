from app.core.config import Settings


def test_settings_load_environment(monkeypatch) -> None:
    monkeypatch.setenv("APP_PORT", "9000")
    monkeypatch.setenv("IMAGE_WORKER_CONCURRENCY", "3")
    monkeypatch.setenv("OPENAI_PROJECT", "proj_test")
    monkeypatch.setenv("ARK_VIDEO_POLL_INTERVAL", "3")
    monkeypatch.setenv("ARK_VIDEO_POLL_NETWORK_RETRIES", "4")
    monkeypatch.setenv("ARK_VIDEO_POLL_RETRY_BASE_DELAY", "1.5")
    monkeypatch.setenv("ARK_VIDEO_MAX_DOWNLOAD_MB", "150")
    settings = Settings(_env_file=None)
    assert settings.app_port == 9000
    assert settings.image_worker_concurrency == 3
    assert settings.redis_url.startswith("redis://")
    assert settings.openai_project == "proj_test"
    assert settings.ark_video_poll_interval == 3
    assert settings.ark_video_poll_network_retries == 4
    assert settings.ark_video_poll_retry_base_delay == 1.5
    assert settings.ark_video_max_download_mb == 150
