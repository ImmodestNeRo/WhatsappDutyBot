"""
Duty queue business logic.

- ``start_day`` and ``rotate_and_penalize`` check ``last_start_date`` /
  ``last_rotation_date`` to avoid double-firing after a restart.
- ``rotate_and_penalize`` is fully atomic — single SafeJSONStorage.update()
  covers penalize + rotate + reset in one lock/fsync.
- All state lives in one ``bot_state.json``; legacy 3-file layout is
  auto-migrated on first run.
- GROUP_JID can be seeded from config on first run.
"""

from __future__ import annotations

import json as _json
import os
from datetime import datetime, timedelta
from typing import Optional

import pytz

from config import config
from .storage import SafeJSONStorage
from .utils import get_logger
from . import messages as msg

logger = get_logger("DutyManager")

TZ = pytz.timezone(config.timezone)

_DEFAULT_STATE: dict = {
    "queue": [],
    "guilty_records": [],
    "current_duty": None,
    "confirmed_today": False,
    "last_rotation_date": None,
    "last_start_date": None,
    "group_jid": None,
}


class DutyManager:
    def __init__(self, data_dir: str | None = None) -> None:
        data_dir = data_dir or config.data_dir
        os.makedirs(data_dir, exist_ok=True)

        self._maybe_migrate(data_dir)

        self.state = SafeJSONStorage(
            os.path.join(data_dir, "bot_state.json"),
            dict(_DEFAULT_STATE),
        )

        # Auto-bind group from .env if not yet persisted
        self._auto_bind_group()
        self._enforce_queue_constraints()

    # ── Migration ──────────────────────────────────────────

    def _maybe_migrate(self, data_dir: str) -> None:
        """Merge legacy 3-file layout into bot_state.json on first run."""
        new_path = os.path.join(data_dir, "bot_state.json")
        if os.path.exists(new_path):
            return

        merged = dict(_DEFAULT_STATE)

        for fname, mapping in [
            ("duty_list.json",    {"queue": "queue"}),
            ("guilty.json",       {"records": "guilty_records"}),
            ("runtime_state.json", {
                "current_duty":       "current_duty",
                "confirmed_today":    "confirmed_today",
                "last_rotation_date": "last_rotation_date",
                "last_start_date":    "last_start_date",
                "group_jid":          "group_jid",
            }),
        ]:
            path = os.path.join(data_dir, fname)
            if not os.path.exists(path):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    data = _json.load(f)
                for old_key, new_key in mapping.items():
                    if old_key in data:
                        merged[new_key] = data[old_key]
            except Exception as exc:
                logger.warning("Migration: could not read %s: %s", fname, exc)

        tmp = new_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(merged, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, new_path)
        logger.info("Migrated legacy files to bot_state.json")

    # ── Auto-binding ───────────────────────────────────────

    def _auto_bind_group(self) -> None:
        """If GROUP_JID is set in config and not yet saved, persist it."""
        env_jid = config.group_jid
        if not env_jid:
            return
        if self.state.read().get("group_jid") != env_jid:
            def _mut(st: dict) -> None:
                st["group_jid"] = env_jid
            self.state.update(_mut)
            logger.info("Auto-bound to group %s from config.", env_jid)

    def _enforce_queue_constraints(self) -> None:
        """Move QUEUE_ALWAYS_LAST to the end if it's not already there."""
        always_last = config.queue_always_last
        if not always_last:
            return
        st = self.state.read()
        queue = st.get("queue", [])
        if always_last in queue and queue[-1] != always_last:
            def _mut(s: dict) -> None:
                s["queue"].remove(always_last)
                s["queue"].append(always_last)
            self.state.update(_mut)
            logger.info("Queue constraint applied: %s moved to end.", always_last)

    # ── Date helpers ───────────────────────────────────────

    @staticmethod
    def is_sunday() -> bool:
        return datetime.now(TZ).weekday() == 6

    @staticmethod
    def get_current_date_str() -> str:
        return datetime.now(TZ).strftime("%Y-%m-%d")

    # ── Group ──────────────────────────────────────────────

    def bind_group(self, group_jid: str) -> None:
        def _mut(st: dict) -> None:
            st["group_jid"] = group_jid
        self.state.update(_mut)
        logger.info("Bot bound to group %s", group_jid)

    def get_group(self) -> Optional[str]:
        return self.state.read().get("group_jid")

    # ── Queue management ───────────────────────────────────

    def get_next_duty(self) -> Optional[str]:
        queue = self.state.read().get("queue", [])
        return queue[0] if queue else None

    def add_to_queue(self, user_base: str) -> bool:
        added = False
        always_last = config.queue_always_last
        def _mut(st: dict) -> None:
            nonlocal added
            if user_base not in st["queue"]:
                st["queue"].append(user_base)
                added = True
            if always_last and always_last in st["queue"] and st["queue"][-1] != always_last:
                st["queue"].remove(always_last)
                st["queue"].append(always_last)
        self.state.update(_mut)
        return added

    def get_queue(self) -> list[str]:
        return self.state.read().get("queue", [])

    def get_queue_with_dates(self, limit: int | None = 10) -> list[dict]:
        """Calculates dates for the next users in the queue, skipping Sundays."""
        queue = self.get_queue()
        if not queue:
            return []

        results = []
        today = datetime.now(TZ)
        current_date = today

        days_ukr = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]

        for i, user in enumerate(queue if limit is None else queue[:limit]):
            if current_date.weekday() == 6:
                current_date += timedelta(days=1)

            results.append({
                "date": current_date.strftime("%d.%m"),
                "day": days_ukr[current_date.weekday()],
                "user": user,
                "is_today": i == 0 and current_date.date() == today.date()
            })

            current_date += timedelta(days=1)

        return results

    def remove_from_queue(self, user_phone: str) -> bool:
        """Removes a user from the queue by their phone number."""
        removed = False
        def _mut(st: dict) -> None:
            nonlocal removed
            if user_phone in st["queue"]:
                st["queue"].remove(user_phone)
                removed = True
        self.state.update(_mut)
        return removed

    # ── Duty confirmation ──────────────────────────────────

    def confirm_duty(self, user_base: str) -> tuple[bool, str]:
        if self.is_sunday():
            return False, msg.SUNDAY_NO_DUTY

        st = self.state.read()
        logger.info("confirm_duty: current_duty=%r caller=%r", st.get("current_duty"), user_base)
        if st.get("current_duty") == user_base:
            if st.get("confirmed_today"):
                return False, msg.DUTY_ALREADY_CONFIRMED
            def _mut(s: dict) -> None:
                s["confirmed_today"] = True
            self.state.update(_mut)
            return True, msg.DUTY_CONFIRMED
        return False, msg.NOT_YOUR_DUTY

    def get_guilty(self) -> list[dict]:
        return self.state.read().get("guilty_records", [])

    # ── Daily lifecycle ────────────────────────────────────

    def start_day(self) -> Optional[str]:
        """Assign the duty person for today.

        Returns the user string, or ``None`` if it's Sunday or the
        assignment was already done today.
        """
        if self.is_sunday():
            return None

        today = self.get_current_date_str()
        st = self.state.read()

        if st.get("last_start_date") == today:
            logger.info("start_day already ran for %s, skipping.", today)
            return None

        next_user = self.get_next_duty()
        if next_user:
            def _mut(s: dict) -> None:
                s["current_duty"] = next_user
                s["confirmed_today"] = False
                s["last_start_date"] = today
            self.state.update(_mut)
        return next_user

    def is_confirmed_today(self) -> bool:
        return self.state.read().get("confirmed_today", False)

    def get_current_assigned(self) -> Optional[str]:
        return self.state.read().get("current_duty")

    # ── End-of-day rotation ────────────────────────────────

    def rotate_and_penalize(self) -> None:
        """Penalize if unconfirmed, rotate queue, reset state — atomically.

        Single update() call: one lock, one fsync, no partial-write risk.
        Guarded by ``last_rotation_date`` to avoid double rotation on restart.
        """
        if self.is_sunday():
            return

        today = self.get_current_date_str()

        # Guard: already rotated today
        if self.state.read().get("last_rotation_date") == today:
            logger.info("rotate_and_penalize already ran for %s, skipping.", today)
            return

        def _mutate(st: dict) -> None:
            # 1. Penalize if not confirmed
            if not st.get("confirmed_today", False) and st.get("current_duty"):
                st["guilty_records"].append({
                    "date": today,
                    "user": st["current_duty"],
                })
                logger.info("Penalized %s for missing duty on %s.", st["current_duty"], today)

            # 2. Rotate queue
            if st["queue"]:
                st["queue"].append(st["queue"].pop(0))

            # 3. Reset state — current_duty is set fresh by start_day next morning
            st["current_duty"] = None
            st["confirmed_today"] = False
            st["last_rotation_date"] = today

        self.state.update(_mutate)
        logger.info("Rotated queue. New head: %s", self.get_next_duty())
