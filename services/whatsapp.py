"""
WhatsApp client: event handling, message parsing, command dispatch.

- History-sync grace period is configurable (default 60 s).
- client_jid resolved eagerly in on_connected(), not lazily.
- Commands registered in a dict — adding a new command = one new method.
- All user-facing strings come from ``messages.py``.
"""

from __future__ import annotations

import json
import time
from typing import Callable, Optional

import segno
from neonize.client import NewClient
from neonize.events import ConnectedEv, DisconnectedEv, MessageEv, QREv
import neonize.proto.waE2E.WAWebProtobufsE2E_pb2 as pb
import neonize.proto.Neonize_pb2 as neonize_pb
from neonize.utils.enum import VoteType

from config import config
from .duty import DutyManager
from .utils import get_logger, with_retry
from . import messages as msg

logger = get_logger("WhatsAppService")


class WhatsAppClient:
    def __init__(self, duty_manager: DutyManager) -> None:
        self.duty_manager = duty_manager
        self.client = NewClient(config.session_db_path)
        self.client_jid: Optional[str] = None
        self.boot_time: int = int(time.time())
        self.on_ready: Optional[Callable] = None

        # Register core events
        self.client.event(MessageEv)(self.on_message)
        self.client.event(QREv)(self.on_qr)
        self.client.event(ConnectedEv)(self.on_connected)
        self.client.event(DisconnectedEv)(self.on_disconnected)

        # Command dispatch table
        self._handlers: dict[str, Callable] = {
            "/bind_group": self._cmd_bind_group,
            "/add":        self._cmd_add,
            "/remove":     self._cmd_remove,
            "/list":       self._cmd_list,
            "/guilty":     self._cmd_guilty,
            "/done":       self._cmd_done,
        }

    # ── Event handlers ─────────────────────────────────────

    def on_qr(self, client: NewClient, event: QREv) -> None:
        logger.info("QR CODE RECEIVED — scan with your WhatsApp!")
        for code in event.Codes:
            qr = segno.make(code)
            print("\n")
            qr.terminal()
            print("\n")

    def on_connected(self, client: NewClient, event: ConnectedEv) -> None:
        logger.info("WhatsApp connected successfully.")
        try:
            me = client.get_me()
            if me:
                me_jid = getattr(me, "JID", None)
                if me_jid:
                    self.client_jid = f"{me_jid.User}@{me_jid.Server}"
                    logger.info("Own JID resolved: %s", self.client_jid)
        except Exception as exc:
            logger.warning("Could not resolve own JID: %s", exc)

        if self.on_ready:
            try:
                self.on_ready()
                self.on_ready = None  # fire once only
            except Exception as exc:
                logger.error("Catch-up error: %s", exc, exc_info=True)

    def on_disconnected(self, client: NewClient, event: DisconnectedEv) -> None:
        logger.warning("WhatsApp session disconnected!")

    # ── JID helpers ────────────────────────────────────────

    @staticmethod
    def _parse_jid(jid_str: str) -> neonize_pb.JID:
        parts = jid_str.split("@")
        if len(parts) == 2:
            return neonize_pb.JID(
                User=parts[0], Server=parts[1],
                RawAgent=0, Device=0, Integrator=0,
            )
        return neonize_pb.JID(
            User=jid_str, Server="s.whatsapp.net",
            RawAgent=0, Device=0, Integrator=0,
        )

    def _resolve_phone(self, sender_user: str, sender_server: str) -> Optional[str]:
        """Try to get a real phone number from a sender's JID.

        WhatsApp now sends LID identifiers (e.g. 68634181431386@lid) in
        groups instead of the real phone number. This method tries to
        reverse-lookup the phone number via neonize's get_pn_from_lid.
        Returns the phone string on success, or None if it can't resolve.
        """
        if sender_server != "lid":
            return sender_user
        try:
            lid_jid = self._parse_jid(f"{sender_user}@{sender_server}")
            pn = self.client.get_pn_from_lid(lid_jid)
            if pn:
                phone = getattr(pn, "User", "").strip().lstrip("+")
                if phone:
                    logger.info("Resolved LID %s → phone %s", sender_user, phone)
                    return phone
        except Exception as exc:
            logger.warning("LID resolution failed for %s: %s", sender_user, exc)
        return None

    # ── Sending ────────────────────────────────────────────

    @with_retry(max_retries=3)
    def send_text(self, jid: str, text: str) -> None:
        logger.info("Sending text to %s", jid)
        self.client.send_message(self._parse_jid(jid), text)

    @with_retry(max_retries=3)
    def send_done_button(self, jid: str, text_content: str) -> None:
        """Send a plain text message instructing the user to use /done."""
        logger.info("Sending simple text notification to %s", jid)
        message = f"{text_content}\n\n👉 Напишіть /done коли закінчите."
        self.send_text(jid, message)

    # ── Incoming message handler ───────────────────────────

    def on_message(self, client: NewClient, message: MessageEv) -> None:
        try:
            text = self._extract_text(message)
            if text is None:
                return

            info = getattr(message, "Info", getattr(message, "info", None))
            ms = getattr(info, "MessageSource", getattr(info, "messageSource", None))
            chat = getattr(ms, "Chat", None)
            sender = getattr(ms, "Sender", None)

            chat_jid = f"{chat.User}@{chat.Server}"

            self._dispatch_command(text, chat_jid, sender, message)

        except Exception as exc:
            logger.error("Error handling message: %s", exc, exc_info=True)

    def _extract_text(self, message: MessageEv) -> Optional[str]:
        """Parse raw MessageEv → plain text string (or None to skip)."""
        info = getattr(message, "Info", getattr(message, "info", None))
        if not info:
            return None

        # ── History-sync filter ────────────────────────────
        msg_ts = getattr(info, "Timestamp", 0)
        if msg_ts and msg_ts < self.boot_time - config.history_sync_grace:
            return None

        ms = getattr(info, "MessageSource", getattr(info, "messageSource", None))
        if not ms:
            return None

        chat = getattr(ms, "Chat", None)
        sender = getattr(ms, "Sender", None)
        if not chat or not sender:
            return None

        sender_jid = f"{sender.User}@{sender.Server}"

        # Anti-loop
        if self.client_jid and sender_jid == self.client_jid:
            return None

        # Groups only
        if chat.Server != "g.us":
            return None

        raw_msg = getattr(message, "Message", None)
        if not raw_msg:
            return None

        # Plain text
        text = getattr(raw_msg, "conversation", "")
        if not text:
            ext = getattr(raw_msg, "extendedTextMessage", None)
            if ext:
                text = getattr(ext, "text", "")

        # Button response
        if not text:
            inter = getattr(raw_msg, "interactiveResponseMessage", None)
            if inter:
                flow = getattr(inter, "nativeFlowResponseMessage", None)
                if flow:
                    p_json = getattr(flow, "paramsJSON", "{}")
                    try:
                        parsed = json.loads(p_json)
                        if parsed.get("id") == "cmd_done":
                            text = "/done"
                    except (json.JSONDecodeError, KeyError) as exc:
                        logger.debug("Failed to parse button response: %s", exc)

        # Poll response fallback
        if not text:
            poll_update = getattr(raw_msg, "pollUpdateMessage", None)
            if poll_update:
                logger.info("Received a poll vote! Interpreting as confirmation.")
                text = "/done"

        return text if text else None

    def _get_user_from_command(self, text: str, message: MessageEv) -> Optional[str]:
        """
        Extracts a phone number from the command, either from a mention
        or from a direct numeric string.
        """
        # 1. Check for mentions in contextInfo
        try:
            raw_msg = getattr(message, "Message", None)
            ext = getattr(raw_msg, "extendedTextMessage", None)
            if ext and ext.contextInfo and ext.contextInfo.mentionedJid:
                mention_jid = ext.contextInfo.mentionedJid[0]
                parts = mention_jid.split("@")
                user = parts[0]
                server = parts[1] if len(parts) > 1 else "s.whatsapp.net"
                return self._resolve_phone(user, server)
        except Exception as exc:
            logger.debug("Failed to extract mention: %s", exc)

        # 2. Check for manual phone number in text
        parts = text.strip().split(maxsplit=1)
        if len(parts) >= 2:
            phone = parts[1].strip().lstrip("+").replace("-", "").replace(" ", "")
            if phone.isdigit() and len(phone) >= 10:
                return phone

        return None

    # ── Command dispatch ───────────────────────────────────

    def _dispatch_command(self, text: str, chat_jid: str, sender: object, message: MessageEv) -> None:
        """Route a text command to the appropriate handler."""
        parts = text.strip().split(maxsplit=1)
        if not parts:
            return
        handler = self._handlers.get(parts[0])
        if handler:
            handler(text, chat_jid, sender, message)

    # ── Command handlers ───────────────────────────────────

    def _cmd_bind_group(self, text: str, chat_jid: str, sender: object, message: MessageEv) -> None:
        self.duty_manager.bind_group(chat_jid)
        self.send_text(chat_jid, msg.GROUP_BOUND)

    def _cmd_add(self, text: str, chat_jid: str, sender: object, message: MessageEv) -> None:
        phone = self._get_user_from_command(text, message)

        if not phone:
            sender_user: str = getattr(sender, "User", "")
            sender_server: str = getattr(sender, "Server", "s.whatsapp.net")
            phone = self._resolve_phone(sender_user, sender_server)

        if phone:
            if self.duty_manager.add_to_queue(phone):
                self.send_text(chat_jid, msg.ADDED_TO_QUEUE)
            else:
                self.send_text(chat_jid, msg.ALREADY_IN_QUEUE)
        else:
            self.send_text(chat_jid, msg.ADD_USAGE)

    def _cmd_remove(self, text: str, chat_jid: str, sender: object, message: MessageEv) -> None:
        phone = self._get_user_from_command(text, message)

        if phone:
            if self.duty_manager.remove_from_queue(phone):
                self.send_text(chat_jid, msg.REMOVED_FROM_QUEUE.format(user=phone))
            else:
                self.send_text(chat_jid, msg.NOT_IN_QUEUE.format(user=phone))
        else:
            self.send_text(chat_jid, msg.REMOVE_USAGE)

    def _cmd_list(self, text: str, chat_jid: str, sender: object, message: MessageEv) -> None:
        queue_data = self.duty_manager.get_queue_with_dates(limit=10)
        if not queue_data:
            self.send_text(chat_jid, msg.QUEUE_EMPTY)
        else:
            lines = []
            for item in queue_data:
                prefix = "✅ " if item["is_today"] else "— "
                suffix = " (Сьогодні)" if item["is_today"] else ""
                lines.append(f"{item['day']} ({item['date']}) {prefix}@{item['user']}{suffix}")
            self.send_text(chat_jid, f"{msg.QUEUE_HEADER}\n" + "\n".join(lines))

    def _cmd_guilty(self, text: str, chat_jid: str, sender: object, message: MessageEv) -> None:
        records = self.duty_manager.get_guilty()
        if not records:
            self.send_text(chat_jid, msg.GUILTY_EMPTY)
        else:
            lines = [f"{r['date']}: @{r['user']}" for r in records]
            self.send_text(chat_jid, f"{msg.GUILTY_HEADER}\n" + "\n".join(lines))

    def _cmd_done(self, text: str, chat_jid: str, sender: object, message: MessageEv) -> None:
        sender_user: str = getattr(sender, "User", "")
        sender_server: str = getattr(sender, "Server", "s.whatsapp.net")
        caller_phone = self._resolve_phone(sender_user, sender_server) or sender_user
        logger.info(
            "/done: sender_user=%s server=%s resolved_phone=%s",
            sender_user, sender_server, caller_phone,
        )
        success, response_text = self.duty_manager.confirm_duty(caller_phone)
        self.send_text(chat_jid, response_text)

    # ── Connection ─────────────────────────────────────────

    def connect(self) -> None:
        logger.info("Connecting to WhatsApp…")
        self.client.connect()
