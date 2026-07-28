import logging
from typing import Any

import app.core.logging as logging_config


def test_http_client_info_logs_are_disabled_to_protect_signed_urls(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        logging_config,
        "dictConfig",
        lambda config: captured.update(config),
    )

    logging_config.configure_logging()

    assert captured["loggers"]["httpx"] == {
        "handlers": ["console"],
        "level": logging.WARNING,
        "propagate": False,
    }
    assert captured["loggers"]["httpcore"] == {
        "handlers": ["console"],
        "level": logging.WARNING,
        "propagate": False,
    }


def test_worker_http_client_log_levels_are_set_without_importing_fastapi(
    monkeypatch,
) -> None:
    levels: dict[str, int] = {}

    class FakeLogger:
        def __init__(self, name: str):
            self.name = name

        def setLevel(self, level: int) -> None:
            levels[self.name] = level

    original_get_logger = logging_config.logging.getLogger
    monkeypatch.setattr(
        logging_config.logging,
        "getLogger",
        lambda name=None: (
            original_get_logger() if name is None else FakeLogger(name)
        ),
    )

    logging_config.configure_http_client_logging()

    assert levels == {
        "httpx": logging.WARNING,
        "httpcore": logging.WARNING,
    }
