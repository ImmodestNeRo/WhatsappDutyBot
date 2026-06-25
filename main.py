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
from services.utils import get_logger, send_telegram_alert
from services.duty import DutyManager
from services.whatsapp import WhatsAppClient
from services.scheduler import BotScheduler

logger = get_logger("Main")


def _outage_alert(text: str) -> None:
    """Out-of-band alert for a real WhatsApp outage (can't notify via WhatsApp
    when WhatsApp itself is down). No-op unless Telegram is configured."""
    if config.telegram_token and config.telegram_chat_id:
        send_telegram_alert(config.telegram_token, config.telegram_chat_id, text)


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

    # If neonize auto-reconnect fires but takes longer than this, force a full reconnect.
    RECONNECT_WATCHDOG = 90  # seconds
    outage_alerted = False  # ensures the outage alert fires at most once per outage

    # 6. Connect with auto-reconnect
    while True:
        try:
            logger.info("Connecting to WhatsApp…")
            wa_client.connect()
            logger.info("Connected. Listening for events…")

            # Keep alive; watchdog exits inner loop when neonize auto-reconnect fails.
            while True:
                time.sleep(5)
                if not wa_client._connected and wa_client._disconnected_at > 0:
                    elapsed = time.time() - wa_client._disconnected_at
                    if elapsed > RECONNECT_WATCHDOG:
                        if not outage_alerted:
                            logger.error("Sustained WhatsApp outage (%.0f s).", elapsed)
                            _outage_alert(
                                "⚠️ DutyBot втратив зв'язок з WhatsApp більш ніж на "
                                f"{RECONNECT_WATCHDOG} с і не може автоматично перепідключитися.\n\n"
                                "Можливо, потрібен повторний QR-код: Railway → сервіс → Logs."
                            )
                            outage_alerted = True
                        logger.warning(
                            "No auto-reconnect for %.0f s — forcing reconnect.", elapsed
                        )
                        break
                elif wa_client._connected and outage_alerted:
                    # Recovered after a real outage — report once.
                    logger.info("WhatsApp connection recovered after outage.")
                    _outage_alert("✅ DutyBot відновив зв'язок з WhatsApp.")
                    outage_alerted = False

        except KeyboardInterrupt:
            logger.info("Shutting down gracefully.")
            sys.exit(0)
        except Exception as exc:
            logger.error("Connection error: %s", exc, exc_info=True)
            logger.info("Reconnecting in 10 s…")
            time.sleep(10)


if __name__ == "__main__":
    run()