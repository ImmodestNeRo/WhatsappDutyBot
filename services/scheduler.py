"""
APScheduler-based cron scheduler.

All times are read from ``config`` so you can tweak them via ``.env``
without rebuilding Docker.
"""

from __future__ import annotations

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
        h, m = config.parse_time(config.schedule_morning)
        self.scheduler.add_job(
            self.job_morning, trigger="cron", hour=h, minute=m,
            misfire_grace_time=MISFIRE_GRACE,
        )

        h, m = config.parse_time(config.schedule_reminder_1)
        self.scheduler.add_job(
            self.job_reminder, trigger="cron", hour=h, minute=m,
            misfire_grace_time=MISFIRE_GRACE,
        )

        h, m = config.parse_time(config.schedule_reminder_2)
        self.scheduler.add_job(
            self.job_reminder, trigger="cron", hour=h, minute=m,
            misfire_grace_time=MISFIRE_GRACE,
        )

        h, m = config.parse_time(config.schedule_end_of_day)
        self.scheduler.add_job(
            self.job_end_of_day, trigger="cron", hour=h, minute=m,
            misfire_grace_time=MISFIRE_GRACE,
        )

        logger.info(
            "Jobs: morning=%s, rem1=%s, rem2=%s, eod=%s",
            config.schedule_morning, config.schedule_reminder_1,
            config.schedule_reminder_2, config.schedule_end_of_day,
        )

    # ── Jobs ───────────────────────────────────────────────

    def job_morning(self) -> None:
        try:
            gid = self.duty.get_group()
            if not gid:
                logger.warning("Morning job skipped — no group bound.")
                return

            user = self.duty.start_day()
            if user:
                text = msg.MORNING_ANNOUNCEMENT.format(user=user)
                self.wa.send_done_button(gid, text)
        except Exception as exc:
            logger.error("Error in morning job: %s", exc, exc_info=True)

    def job_reminder(self) -> None:
        try:
            gid = self.duty.get_group()
            if not gid:
                return

            if not self.duty.is_confirmed_today() and not self.duty.is_sunday():
                user = self.duty.get_current_assigned()
                if user:
                    text = msg.REMINDER.format(user=user)
                    self.wa.send_done_button(gid, text)
        except Exception as exc:
            logger.error("Error in reminder job: %s", exc, exc_info=True)

    def job_end_of_day(self) -> None:
        try:
            self.duty.rotate_and_penalize()
        except Exception as exc:
            logger.error("Error in end-of-day job: %s", exc, exc_info=True)

    # ── Lifecycle ──────────────────────────────────────────

    def start(self) -> None:
        self.scheduler.start()
        logger.info("Scheduler started.")
