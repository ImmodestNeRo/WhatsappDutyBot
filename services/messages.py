"""
All user-facing bot messages in one place.

To change the "voice" of the bot, edit this file only — no code changes needed.
Placeholders use Python str.format() syntax: {user}, {date}, etc.
"""

from __future__ import annotations

# ── Scheduler / automatic messages ─────────────────────────
MORNING_ANNOUNCEMENT = (
    "Доброго ранку! Сьогодні черговий: @{user}\n"
    "Натисніть кнопку по завершенню."
)

REMINDER = "Нагадування для @{user}: Ви ще не завершили чергування!"

SUNDAY_MESSAGE = "Сьогодні неділя — вихідний. 🌞"

# ── Command responses ──────────────────────────────────────
GROUP_BOUND = "✅ Ця група прикріплена для чергувань."

ADDED_TO_QUEUE = "✅ Вас додано до черги!"
ALREADY_IN_QUEUE = "Ви вже в черзі."
ADD_USAGE = "Вкажіть свій номер телефону:\n/add 380663644854"
ADD_INVALID_PHONE = "❌ Невірний формат номера.\nПриклад: /add 380663644854"

QUEUE_EMPTY = "Черга порожня."
QUEUE_HEADER = "Поточна черга:"

GUILTY_EMPTY = "Порушників немає. 🎉"
GUILTY_HEADER = "Список порушників:"

DUTY_CONFIRMED = "✅ Чергування підтверджено!"
NOT_YOUR_DUTY = "Ви не є черговим сьогодні."
SUNDAY_NO_DUTY = "Сьогодні неділя, вихідний."

# ── Button labels ──────────────────────────────────────────
BUTTON_CONFIRM = "✅ Підтвердити"
