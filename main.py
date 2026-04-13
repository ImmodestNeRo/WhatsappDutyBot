"""
DutyBot entry point.

Loads .env, wires up components, and runs the WhatsApp connection loop
with automatic reconnection.
"""

from __future__ import annotations

import os
import sys
import time

# Load .env BEFORE anything else reads os.environ
from dotenv import load_dotenv
load_dotenv()

from config import config
from services.utils import get_logger
from services.duty import DutyManager
from services.whatsapp import WhatsAppClient
from services.scheduler import BotScheduler

logger = get_logger("Main")


def run() -> None:
    logger.info("Starting DutyBot…")
    logger.info("Data dir: %s | TZ: %s", config.data_dir, config.timezone)

    # 1. Ensure data directory exists
    os.makedirs(config.data_dir, exist_ok=True)

    # 2. Business logic
    duty_manager = DutyManager()

    # 3. WhatsApp client
    wa_client = WhatsAppClient(duty_manager)

    # 4. Check if first-time QR auth is needed
    if not os.path.exists(config.session_db_path):
        logger.warning("No session.db found — QR auth required!")
        try:
            print("\n" + "=" * 60)
            ans = input("[!!!] Бот потребує прив'язки WhatsApp. Згенерувати QR? (y/n): ")
            print("=" * 60 + "\n")
            if ans.strip().lower() != "y":
                logger.info("Cancelled by user.")
                sys.exit(0)
        except EOFError:
            logger.warning("No interactive input — proceeding with QR automatically.")

    # 5. Scheduler (reads times from config/.env)
    scheduler = BotScheduler(duty_manager, wa_client)
    scheduler.start()
    wa_client.on_ready = scheduler.catchup

    # 6. Connect with auto-reconnect
    while True:
        try:
            logger.info("Connecting to WhatsApp…")
            wa_client.connect()
            logger.info("Connected. Listening for events…")

            # Keep alive
            while True:
                time.sleep(1)

        except KeyboardInterrupt:
            logger.info("Shutting down gracefully.")
            sys.exit(0)
        except Exception as exc:
            logger.error("Connection error: %s", exc, exc_info=True)
            logger.info("Reconnecting in 10 s…")
            time.sleep(10)


if __name__ == "__main__":
    run()