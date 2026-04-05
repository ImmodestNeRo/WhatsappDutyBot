"""
Duty queue business logic.

Key improvements over the original:
- ``start_day`` and ``rotate_and_penalize`` check ``last_start_date`` /
  ``last_rotation_date`` to avoid double-firing after a restart.
- ``rotate_and_penalize`` is atomic — reads all state, computes changes,
  writes everything in one batch.
- GROUP_JID can be seeded from config on first run.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

import pytz

from config import config
from .storage import SafeJSONStorage
from .utils import get_logger
from . import messages as msg

logger = get_logger("DutyManager")

TZ = pytz.timezone(config.timezone)


class DutyManager:
    def __init__(self, data_dir: str | None = None) -> None:
        data_dir = data_dir or config.data_dir
        os.makedirs(data_dir, exist_ok=True)

        self.duty_list = SafeJSONStorage(
            os.path.join(data_dir, "duty_list.json"),
            {"queue": []},
        )
        self.guilty = SafeJSONStorage(
            os.path.join(data_dir, "guilty.json"),
            {"records": []},
        )
        self.runtime_state = SafeJSONStorage(
            os.path.join(data_dir, "runtime_state.json"),
            {
                "current_duty": None,
                "last_rotation_date": None,
                "last_start_date": None,
                "confirmed_today": False,
                "group_jid": None,
            },
        )

        # Auto-bind group from .env if not yet persisted
        self._auto_bind_group()

    # ── Auto-binding ───────────────────────────────────────

    def _auto_bind_group(self) -> None:
        """If GROUP_JID is set in config and not yet saved, persist it."""
        env_jid = config.group_jid
        if not env_jid:
            return
        state = self.runtime_state.read()
        if state.get("group_jid") != env_jid:
            def _mut(st: dict) -> None:
                st["group_jid"] = env_jid
            self.runtime_state.update(_mut)
            logger.info("Auto-bound to group %s from config.", env_jid)

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
        self.runtime_state.update(_mut)
        logger.info("Bot bound to group %s", group_jid)

    def get_group(self) -> Optional[str]:
        return self.runtime_state.read().get("group_jid")

    # ── Queue management ───────────────────────────────────

    def get_next_duty(self) -> Optional[str]:
        queue = self.duty_list.read().get("queue", [])
        return queue[0] if queue else None

    def add_to_queue(self, user_base: str) -> bool:
        added = False
        def _mut(dt: dict) -> None:
            nonlocal added
            if user_base not in dt["queue"]:
                dt["queue"].append(user_base)
                added = True
        self.duty_list.update(_mut)
        return added

    def get_queue(self) -> list[str]:
        return self.duty_list.read().get("queue", [])

    # ── Duty confirmation ──────────────────────────────────

    def confirm_duty(self, user_base: str) -> tuple[bool, str]:
        if self.is_sunday():
            return False, msg.SUNDAY_NO_DUTY

        state = self.runtime_state.read()
        if state.get("current_duty") == user_base:
            def _mut(st: dict) -> None:
                st["confirmed_today"] = True
            self.runtime_state.update(_mut)
            return True, msg.DUTY_CONFIRMED
        return False, msg.NOT_YOUR_DUTY

    def get_guilty(self) -> list[dict]:
        return self.guilty.read().get("records", [])

    # ── Daily lifecycle ────────────────────────────────────

    def start_day(self) -> Optional[str]:
        """Assign the duty person for today.

        Returns the user string, or ``None`` if it's Sunday or the
        assignment was already done today.
        """
        if self.is_sunday():
            return None

        today = self.get_current_date_str()
        state = self.runtime_state.read()

        # Guard: already started today (e.g. bot restarted mid-day)
        if state.get("last_start_date") == today:
            logger.info("start_day already ran for %s, skipping.", today)
            return state.get("current_duty")

        next_user = self.get_next_duty()
        if next_user:
            def _mut(st: dict) -> None:
                st["current_duty"] = next_user
                st["confirmed_today"] = False
                st["last_start_date"] = today
            self.runtime_state.update(_mut)
        return next_user

    def is_confirmed_today(self) -> bool:
        return self.runtime_state.read().get("confirmed_today", True)

    def get_current_assigned(self) -> Optional[str]:
        return self.runtime_state.read().get("current_duty")

    # ── End-of-day rotation ────────────────────────────────

    def rotate_and_penalize(self) -> None:
        """Penalize if unconfirmed, rotate queue, reset state.

        Guarded by ``last_rotation_date`` to avoid double rotation on
        restart.  All three stores are written together to stay consistent.
        """
        if self.is_sunday():
            return

        today = self.get_current_date_str()
        state = self.runtime_state.read()

        # Guard: already rotated today
        if state.get("last_rotation_date") == today:
            logger.info("rotate_and_penalize already ran for %s, skipping.", today)
            return

        confirmed = state.get("confirmed_today", True)
        current_duty = state.get("current_duty")

        # 1. Penalize if not confirmed
        if not confirmed and current_duty:
            def _pg(g: dict) -> None:
                g["records"].append({
                    "date": today,
                    "user": current_duty,
                })
            self.guilty.update(_pg)
            logger.info("Penalized %s for missing duty on %s.", current_duty, today)

        # 2. Rotate queue
        def _rotate(dt: dict) -> None:
            if dt["queue"]:
                first = dt["queue"].pop(0)
                dt["queue"].append(first)
        self.duty_list.update(_rotate)

        # 3. Reset state with new duty + rotation date
        new_duty = self.get_next_duty()
        def _reset(st: dict) -> None:
            st["confirmed_today"] = False
            st["current_duty"] = new_duty
            st["last_rotation_date"] = today
        self.runtime_state.update(_reset)

        logger.info("Rotated queue. New head: %s", new_duty)
