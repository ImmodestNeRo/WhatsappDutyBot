"""
APScheduler-based cron scheduler.

All times are read from ``config`` so you can tweak them via ``.env``
without rebuilding Docker.
"""

from __future__ import annotations

from datetime import datetime

import pytz
from apscheduler.schedulers.background import BackgroundScheduler

from config import config
from .duty import DutyManager
from .utils import get_logger
from . import messages as msg

logger = get_logger("SchedulerService")

# If the bot was down when a job should have fired, still run it
# within this window (seconds).
MISFIRE_GRACE = 300  # 5 minutes


class BotScheduler:
    def __init__(self, duty_manager: DutyManager, wa_client: object) -> None:
        self.duty = duty_manager
        self.wa = wa_client  # WhatsAppClient (avoids circular import)
        self.tz = pytz.timezone(config.timezone)
        self.scheduler = BackgroundScheduler(timezone=self.tz)
        self._setup_jobs()

    def _setup_jobs(self) -> None:
        self._add_job("morning",    config.schedule_morning,    self.job_morning)
        self._add_job("reminder_1", config.schedule_reminder_1, self.job_reminder)
        self._add_job("reminder_2", config.schedule_reminder_2, self.job_reminder)

    def _add_job(self, name: str, time_str: str, func) -> None:
        """Register a cron job and log its scheduled time clearly."""
        if not time_str:
            logger.error(
                "⚠️  Job '%s' — SCHEDULE ENV VAR IS EMPTY! "
                "Job will be scheduled at 00:00 (midnight). "
                "Set the correct value in .env and restart.",
                name,
            )
        h, m = config.parse_time(time_str)
        self.scheduler.add_job(
            func, trigger="cron", hour=h, minute=m,
            misfire_grace_time=MISFIRE_GRACE,
        )
        logger.info("📅 Job %-12s → %02d:%02d", name, h, m)

    # ── Jobs ───────────────────────────────────────────────

    def job_morning(self) -> None:
        """Close yesterday's duty (rotate + penalize), then assign today's.

        Each step has its own idempotency guard, so a restart mid-job
        won't double-fire either half.
        """
        try:
            # 1. Close previous duty period (24 h window is over)
            self.duty.rotate_and_penalize()

            # 2. Assign today's duty
            gid = self.duty.get_group()
            if not gid:
                logger.warning("Morning job skipped announcement — no group bound.")
                return

            user = self.duty.start_day()
            if user:
                text = msg.MORNING_ANNOUNCEMENT.format(user=user)
                logger.info("Morning announcement for user %s in group %s", user, gid)
                self.wa.send_done_button(gid, text, mentions=[user])
            elif self.duty.is_sunday():
                logger.info("Morning job: Sunday — sending day-off message.")
                self.wa.send_text(gid, msg.SUNDAY_MESSAGE)
            else:
                logger.info("Morning job: start_day() skipped (already ran today or empty queue).")
        except Exception as exc:
            logger.error("Error in morning job: %s", exc, exc_info=True)

    def job_reminder(self) -> None:
        try:
            gid = self.duty.get_group()
            if not gid:
                logger.warning("Reminder job skipped — no group bound.")
                return

            if self.duty.is_sunday():
                return

            if not self.duty.is_confirmed_today():
                user = self.duty.get_current_assigned()
                if user:
                    text = msg.REMINDER.format(user=user)
                    logger.info("Sending reminder to %s for user %s", gid, user)
                    self.wa.send_done_button(gid, text, mentions=[user])
                else:
                    logger.warning("Reminder job: no current_duty assigned (morning job may have skipped).")
        except Exception as exc:
            logger.error("Error in reminder job: %s", exc, exc_info=True)

    # ── Catch-up ───────────────────────────────────────────

    def catchup(self) -> None:
        """Fire missed morning job after WhatsApp connects.

        The morning job itself handles both rotate_and_penalize() and
        start_day(), each with its own idempotency guard. So a single
        call here is enough to close any missed previous day AND assign
        today's duty.
        """
        if self.duty.is_sunday():
            logger.info("Catch-up: Sunday — nothing to do.")
            return

        now = datetime.now(self.tz)
        today = now.strftime("%Y-%m-%d")
        st = self.duty.state.read()

        h, m = config.parse_time(config.schedule_morning)
        if (now.hour, now.minute) >= (h, m) and st.get("last_start_date") != today:
            logger.info("Catch-up: firing morning job.")
            self.job_morning()

    # ── Lifecycle ──────────────────────────────────────────

    def start(self) -> None:
        self.scheduler.start()
        logger.info("Scheduler started.")
