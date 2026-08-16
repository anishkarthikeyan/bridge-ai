"""Structured logging setup. Called once from `main.create_app()`, before anything else runs,
so every log line — including startup — goes through the same handler and format.
"""

import logging
import sys

from app.infrastructure.config import get_settings


def configure_logging() -> None:
    settings = get_settings()
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)s :: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    root.handlers = [handler]

    # Quiet noisy third-party access logs; keep our own logger tree at the configured level.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
