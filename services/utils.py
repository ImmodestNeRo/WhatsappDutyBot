"""
Shared utilities: logging setup, retry decorator, rate limiter.
"""

from __future__ import annotations

import functools
import logging
import os
import sys
import time
from collections import defaultdict, deque
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


class RateLimiter:
    """Sliding-window rate limiter. Thread-safe for single-process bots.

    Example: RateLimiter(max_calls=5, window=60) allows 5 commands per minute per user.
    On violation returns False; the caller decides whether to warn or silently ignore.
    Repeated violations (warn_once=True) only produce one warning per window.
    """

    def __init__(self, max_calls: int, window: int) -> None:
        self.max_calls = max_calls
        self.window = window
        self._history: dict[str, deque] = defaultdict(deque)
        self._warned: dict[str, float] = {}

    def is_allowed(self, user_id: str) -> bool:
        now = time.monotonic()
        q = self._history[user_id]
        while q and q[0] < now - self.window:
            q.popleft()
        if len(q) >= self.max_calls:
            return False
        q.append(now)
        return True

    def should_warn(self, user_id: str) -> bool:
        """True only on the first violation within a window (warn once)."""
        now = time.monotonic()
        last = self._warned.get(user_id, 0.0)
        if now - last > self.window:
            self._warned[user_id] = now
            return True
        return False


def with_retry(max_retries: int = 3, delay: float = 5.0) -> Callable[[F], F]:
    """Retry decorator for transient (network) failures."""
    if max_retries < 1:
        raise ValueError("max_retries must be >= 1")
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
