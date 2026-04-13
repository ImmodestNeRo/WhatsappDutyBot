"""
Centralised configuration for DutyBot.

All tunables are loaded from environment variables (with sane defaults)
so that the bot can be reconfigured via a `.env` file or Docker
`environment:` block — no code changes required.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int = 0) -> int:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class BotConfig:
    """Immutable snapshot of bot configuration."""

    # ── Paths ──────────────────────────────────────────────
    data_dir: str = field(default_factory=lambda: _env("DATA_DIR", "./data"))

    # ── WhatsApp group ─────────────────────────────────────
    # If set, the bot will auto-bind to this group on startup.
    group_jid: str = field(default_factory=lambda: _env("GROUP_JID", ""))

    # ── Timezone ───────────────────────────────────────────
    timezone: str = field(default_factory=lambda: _env("TIMEZONE", "Europe/Kyiv"))

    # ── Schedule (HH:MM format) ────────────────────────────
    # schedule_morning: str = field(default_factory=lambda: _env("SCHEDULE_MORNING", "08:00"))
    # schedule_reminder_1: str = field(default_factory=lambda: _env("SCHEDULE_REMINDER_1", "14:00"))
    # schedule_reminder_2: str = field(default_factory=lambda: _env("SCHEDULE_REMINDER_2", "17:30"))
    # schedule_end_of_day: str = field(default_factory=lambda: _env("SCHEDULE_END_OF_DAY", "23:59"))
    schedule_morning: str = field(default_factory=lambda: _env("SCHEDULE_MORNING", "08:00"))
    schedule_reminder_1: str = field(default_factory=lambda: _env("SCHEDULE_REMINDER_1", "14:00"))
    schedule_reminder_2: str = field(default_factory=lambda: _env("SCHEDULE_REMINDER_2", "17:30"))
    schedule_end_of_day: str = field(default_factory=lambda: _env("SCHEDULE_END_OF_DAY", "23:59"))


    # ── History-sync grace period (seconds) ────────────────
    history_sync_grace: int = field(default_factory=lambda: _env_int("HISTORY_SYNC_GRACE", 60))
    # ── Logging ────────────────────────────────────────────
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))
    log_max_bytes: int = field(default_factory=lambda: _env_int("LOG_MAX_BYTES", 10_485_760))  # 10 MB
    log_backup_count: int = field(default_factory=lambda: _env_int("LOG_BACKUP_COUNT", 5))

    # ── Helpers ────────────────────────────────────────────

    def parse_time(self, value: str) -> tuple[int, int]:
        """Parse 'HH:MM' string into (hour, minute) tuple."""
        if not value or ":" not in value:
            return 0, 0
        parts = value.split(":")
        try:
            return int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            return 0, 0

    @property
    def session_db_path(self) -> str:
        return str(Path(self.data_dir) / "session.db")

    @property
    def log_dir(self) -> str:
        return str(Path(self.data_dir) / "logs")


# ── Singleton ──────────────────────────────────────────────
# Created once at import time; tests can monkeypatch env before importing.
config = BotConfig()
