"""
Shared utilities: logging setup and retry decorator.
"""

from __future__ import annotations

import functools
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from typing import Any, Callable, TypeVar

from config import config

F = TypeVar("F", bound=Callable[..., Any])

_LOGGING_CONFIGURED = False


def setup_logging() -> None:
    """Configure root logger with console + rotating file handlers."""
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return
    _LOGGING_CONFIGURED = True

    log_dir = config.log_dir
    os.makedirs(log_dir, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    level = getattr(logging, config.log_level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    # ── Console handler ────────────────────────────────────
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    # ── Rotating file handler ──────────────────────────────
    file_handler = RotatingFileHandler(
        filename=os.path.join(log_dir, "bot.log"),
        maxBytes=config.log_max_bytes,
        backupCount=config.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Ensures logging is configured first."""
    setup_logging()
    return logging.getLogger(name)


def with_retry(max_retries: int = 3, delay: float = 5.0) -> Callable[[F], F]:
    """Retry decorator for transient (network) failures."""
    _logger = get_logger("retry")

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Exception | None = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    _logger.warning(
                        "%s attempt %d/%d failed: %s",
                        func.__name__, attempt + 1, max_retries, exc,
                    )
                    last_exception = exc
                    if attempt < max_retries - 1:
                        time.sleep(delay)
            _logger.error(
                "%s failed after %d attempts.", func.__name__, max_retries,
            )
            if last_exception is not None:
                raise last_exception
        return wrapper  # type: ignore[return-value]
    return decorator
