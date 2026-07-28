import logging
from logging.config import dictConfig


def configure_http_client_logging() -> None:
    # Celery configures its own root logger and does not import app.main.
    # Keep httpx's full request URL (including signed download queries) out of
    # worker INFO logs while provider-level logs emit sanitized request details.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def configure_logging() -> None:
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                }
            },
            "loggers": {
                # httpx's INFO message contains the full request URL. Ark download
                # URLs are signed, so keep transport logs at WARNING and emit
                # sanitized provider-level HTTP logs instead.
                "httpx": {
                    "handlers": ["console"],
                    "level": logging.WARNING,
                    "propagate": False,
                },
                "httpcore": {
                    "handlers": ["console"],
                    "level": logging.WARNING,
                    "propagate": False,
                },
            },
            "root": {"handlers": ["console"], "level": logging.INFO},
        }
    )
