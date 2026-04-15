"""
WhatsApp client: event handling, message parsing, command dispatch.

- History-sync grace period is configurable (default 60 s).
- client_jid resolved eagerly in on_connected(), not lazily.
- Commands registered in a dict — adding a new command = one new method.
- All user-facing strings come from ``messages.py``.
"""

from __future__ import annotations

import random
import time
from typing import Callable, Optional

import segno
from neonize.client import NewClient
from neonize.events import ConnectedEv, DisconnectedEv, MessageEv, QREv
import neonize.proto.waE2E.WAWebProtobufsE2E_pb2 as pb
import neonize.proto.Neonize_pb2 as neonize_pb
from config import config
from .duty import DutyManager
from .utils import get_logger, with_retry, RateLimiter
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

        self._rate_limiter = RateLimiter(
            max_calls=config.rate_limit_calls,
            window=config.rate_limit_window,
        )

        # Command dispatch table
        self._handlers: dict[str, Callable] = {
            "/bind_group":  self._cmd_bind_group,
            "/add":         self._cmd_add,
            "/remove":      self._cmd_remove,
            "/remove-q":    self._cmd_clear_queue,
            "/remove-g":    self._cmd_clear_guilty,
            "/list":        self._cmd_list,
            "/longlist":    self._cmd_longlist,
            "/guilty":      self._cmd_guilty,
            "/done":        self._cmd_done,
            "/help":        self._cmd_help,
            "/admins-list": self._cmd_admins_list,
            "/trigger":     self._cmd_trigger,
            "/rat":         self._cmd_rat,
            "/swap":        self._cmd_swap,
        }

        # Commands that require admin privileges
        self._admin_commands: set[str] = {
            "/bind_group", "/remove", "/remove-q", "/remove-g",
            "/longlist", "/admins-list", "/trigger", "/guilty",
        }

    # ── Event handlers ─────────────────────────────────────

    def on_qr(self, client: NewClient, event: QREv) -> None:
        logger.info("QR CODE RECEIVED — scan with your WhatsApp!")
        for code in event.Codes:
            qr = segno.make(code)
            print("\n")
            qr.terminal(compact=True)
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
    def send_mentioned_text(self, jid: str, text: str, mentions: list[str]) -> None:
        """Send text with proper WhatsApp @mentions."""
        mention_jids = [f"{m}@s.whatsapp.net" for m in mentions]
        ctx = pb.ContextInfo()
        for mj in mention_jids:
            ctx.mentionedJID.append(mj)
        message = pb.Message(
            extendedTextMessage=pb.ExtendedTextMessage(
                text=text,
                contextInfo=ctx,
            )
        )
        logger.info("Sending mentioned text to %s (mentions: %s)", jid, mentions)
        self.client.send_message(self._parse_jid(jid), message)

    @with_retry(max_retries=3)
    def send_done_button(self, jid: str, text_content: str, mentions: list[str] | None = None) -> None:
        """Send a notification with /done hint. Uses mentions if provided."""
        logger.info("Sending notification to %s", jid)
        full_text = f"{text_content}\n\n👉 Напишіть /done коли закінчите."
        if mentions:
            self.send_mentioned_text(jid, full_text, mentions)
        else:
            self.send_text(jid, full_text)

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

        return text if text else None

    def _get_mentions(self, message: MessageEv) -> list[str]:
        """Extract mentioned phone numbers from WhatsApp mentions."""
        phones: list[str] = []
        try:
            raw_msg = getattr(message, "Message", None)
            ext = getattr(raw_msg, "extendedTextMessage", None)
            if ext and ext.contextInfo and ext.contextInfo.mentionedJID:
                for jid in ext.contextInfo.mentionedJID:
                    parts = jid.split("@")
                    user = parts[0]
                    server = parts[1] if len(parts) > 1 else "s.whatsapp.net"
                    phone = self._resolve_phone(user, server)
                    if phone:
                        phones.append(phone)
        except Exception as exc:
            logger.debug("Failed to extract mentions: %s", exc)
        return phones

    @staticmethod
    def _parse_phone(raw: str) -> Optional[str]:
        """Validate and normalize a single phone number string."""
        phone = raw.strip().lstrip("+").replace("-", "").replace(" ", "").replace(",", "").lstrip("@")
        if phone.isdigit() and 10 <= len(phone) <= 15:
            return phone
        return None

    def _get_users_from_command(self, text: str, message: MessageEv) -> list[str]:
        """Extract phone numbers from mentions and/or text arguments."""
        # 1. Mentions take priority
        phones = self._get_mentions(message)
        if phones:
            return phones

        # 2. Parse phone numbers from text arguments
        parts = text.strip().split()
        for arg in parts[1:]:
            phone = self._parse_phone(arg)
            if phone:
                phones.append(phone)
        return phones

    def _has_args(self, text: str, message: MessageEv) -> bool:
        """Check if the command has any arguments (text or mentions)."""
        if len(text.strip().split()) > 1:
            return True
        return bool(self._get_mentions(message))

    # ── Admin helpers ──────────────────────────────────────

    def _resolve_sender_phone(self, sender: object) -> Optional[str]:
        """Resolve sender object to a phone number string."""
        sender_user: str = getattr(sender, "User", "")
        sender_server: str = getattr(sender, "Server", "s.whatsapp.net")
        return self._resolve_phone(sender_user, sender_server)

    def _is_admin(self, sender: object) -> bool:
        if not config.admin_phones:
            return True  # no admins configured → everyone is admin
        phone = self._resolve_sender_phone(sender)
        return phone in config.admin_phones if phone else False

    # ── Command dispatch ───────────────────────────────────

    def _dispatch_command(self, text: str, chat_jid: str, sender: object, message: MessageEv) -> None:
        """Route a text command to the appropriate handler."""
        parts = text.strip().split(maxsplit=1)
        if not parts:
            return
        cmd = parts[0].lower()
        if cmd not in self._handlers:
            return

        user_id = f"{getattr(sender, 'User', '')}@{getattr(sender, 'Server', '')}"
        if not self._rate_limiter.is_allowed(user_id):
            if self._rate_limiter.should_warn(user_id):
                self.send_text(chat_jid, msg.RATE_LIMITED)
                logger.warning("Rate limit hit by %s", user_id)
            return

        if cmd in self._admin_commands and not self._is_admin(sender):
            self.send_text(chat_jid, msg.NOT_ADMIN)
            return

        self._handlers[cmd](text, chat_jid, sender, message)

    # ── Command handlers ───────────────────────────────────

    def _cmd_bind_group(self, text: str, chat_jid: str, sender: object, message: MessageEv) -> None:
        self.duty_manager.bind_group(chat_jid)
        self.send_text(chat_jid, msg.GROUP_BOUND)

    def _cmd_add(self, text: str, chat_jid: str, sender: object, message: MessageEv) -> None:
        if not self._has_args(text, message):
            # Self-add: no arguments → add the sender
            phone = self._resolve_sender_phone(sender)
            if phone:
                if self.duty_manager.add_to_queue(phone):
                    self.send_text(chat_jid, msg.ADDED_TO_QUEUE)
                else:
                    self.send_text(chat_jid, msg.ALREADY_IN_QUEUE)
            else:
                self.send_text(chat_jid, msg.ADD_USAGE)
            return

        # Adding others requires admin
        if not self._is_admin(sender):
            self.send_text(chat_jid, msg.NOT_ADMIN)
            return

        phones = self._get_users_from_command(text, message)
        if not phones:
            self.send_text(chat_jid, msg.ADD_INVALID_PHONE)
            return

        if len(phones) == 1:
            if self.duty_manager.add_to_queue(phones[0]):
                self.send_text(chat_jid, msg.ADDED_TO_QUEUE)
            else:
                self.send_text(chat_jid, msg.ALREADY_IN_QUEUE)
        else:
            results = []
            for phone in phones:
                if self.duty_manager.add_to_queue(phone):
                    results.append(f"✅ @{phone}")
                else:
                    results.append(f"⏭ @{phone} — вже в черзі")
            self.send_text(chat_jid, "\n".join(results))

    def _cmd_remove(self, text: str, chat_jid: str, sender: object, message: MessageEv) -> None:
        phones = self._get_users_from_command(text, message)
        if not phones:
            self.send_text(chat_jid, msg.REMOVE_USAGE)
            return

        for phone in phones:
            if self.duty_manager.remove_from_queue(phone):
                self.send_text(chat_jid, msg.REMOVED_FROM_QUEUE.format(user=phone))
            else:
                self.send_text(chat_jid, msg.NOT_IN_QUEUE.format(user=phone))

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

    def _cmd_longlist(self, text: str, chat_jid: str, sender: object, message: MessageEv) -> None:
        queue_data = self.duty_manager.get_queue_with_dates(limit=None)
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
            return

        # Count per user
        counts: dict[str, int] = {}
        for r in records:
            counts[r["user"]] = counts.get(r["user"], 0) + 1

        lines = [f"@{user} — {count} пропуск(ів)" for user, count in counts.items()]
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

    def _cmd_clear_queue(self, text: str, chat_jid: str, sender: object, message: MessageEv) -> None:
        self.duty_manager.clear_queue()
        self.send_text(chat_jid, msg.QUEUE_CLEARED)

    def _cmd_clear_guilty(self, text: str, chat_jid: str, sender: object, message: MessageEv) -> None:
        self.duty_manager.clear_guilty()
        self.send_text(chat_jid, msg.GUILTY_CLEARED)

    def _cmd_trigger(self, text: str, chat_jid: str, sender: object, message: MessageEv) -> None:
        user = self.duty_manager.get_current_assigned() or self.duty_manager.get_next_duty()
        if user:
            text_out = msg.REMINDER.format(user=user)
            self.send_done_button(chat_jid, text_out, mentions=[user])
        else:
            self.send_text(chat_jid, msg.NO_CURRENT_DUTY)

    def _cmd_help(self, text: str, chat_jid: str, sender: object, message: MessageEv) -> None:
        lines = [msg.HELP_HEADER, "", *msg.HELP_PUBLIC]
        if self._is_admin(sender):
            lines += ["", *msg.HELP_ADMIN]
        self.send_text(chat_jid, "\n".join(lines))

    def _cmd_admins_list(self, text: str, chat_jid: str, sender: object, message: MessageEv) -> None:
        admins = config.admin_phones
        if not admins:
            self.send_text(chat_jid, msg.NO_ADMINS_CONFIGURED)
        else:
            lines = [msg.ADMINS_HEADER] + [f"• @{a}" for a in admins]
            self.send_mentioned_text(chat_jid, "\n".join(lines), admins)

    # ── Fun commands ───────────────────────────────────────

    def _cmd_rat(self, text: str, chat_jid: str, sender: object, message: MessageEv) -> None:
        admins = set(config.admin_phones)

        phones = self._get_users_from_command(text, message)
        if phones:
            victim = phones[0]
            if victim in admins:
                self.send_text(chat_jid, msg.RAT_ADMIN_PROTECTED)
                return
        else:
            # No argument — pick random non-admin from queue
            queue = [u for u in self.duty_manager.get_queue() if u not in admins]
            if not queue:
                self.send_text(chat_jid, msg.QUEUE_EMPTY)
                return
            victim = random.choice(queue)

        text_out = random.choice(msg.RAT_MESSAGES).format(user=victim)
        self.send_mentioned_text(chat_jid, text_out, [victim])

    def _cmd_swap(self, text: str, chat_jid: str, sender: object, message: MessageEv) -> None:
        self.send_text(chat_jid, msg.SWAP_REQUEST)
        time.sleep(1.5)
        self.send_text(chat_jid, msg.SWAP_DENIED)

    # ── Connection ─────────────────────────────────────────

    def connect(self) -> None:
        logger.info("Connecting to WhatsApp…")
        self.client.connect()
