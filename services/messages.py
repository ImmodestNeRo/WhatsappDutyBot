"""
All user-facing bot messages in one place.

To change the "voice" of the bot, edit this file only — no code changes needed.
Placeholders use Python str.format() syntax: {user}, {date}, etc.
"""

from __future__ import annotations

# ── Scheduler / automatic messages ─────────────────────────
MORNING_ANNOUNCEMENT = (
    "Доброго раночку! Сьогодні черговий: @{user}"
)

REMINDER = "Нагадування для @{user}: Ви ще не завершили чергування!"

SUNDAY_MESSAGE = "Сьогодні неділя — вихідний, а може й ні. 🌞"

# ── Command responses ──────────────────────────────────────
GROUP_BOUND = "✅ Ця група прикріплена для чергувань."

ADDED_TO_QUEUE = "✅ Додано до черги!"
ALREADY_IN_QUEUE = "Вже в черзі."
ADD_USAGE = "Вкажіть свій номер телефону:\n/add 380xxxxxxxxx"
ADD_INVALID_PHONE = "❌ Невірний формат номера /add 380xxxxxxxxx"
REMOVED_FROM_QUEUE = "✅ Користувача @{user} видалено з черги."
NOT_IN_QUEUE = "Користувача @{user} немає в черзі."
REMOVE_USAGE = "Вкажіть номер телефону контакту:\n/remove 380xxxxxxxxx"

QUEUE_EMPTY = "Черга порожня."
QUEUE_HEADER = "Поточна черга:"

GUILTY_EMPTY = "Шкодників немає. 🎉"
GUILTY_HEADER = "Список шкодників:"

DUTY_CONFIRMED = "✅ Чергування підтверджено!"
DUTY_ALREADY_CONFIRMED = "Ви вже відчергували сьогодні."
NOT_YOUR_DUTY = "Ви не є черговим сьогодні."
SUNDAY_NO_DUTY = "Сьогодні неділя, вихідний."

# ── Button labels ──────────────────────────────────────────
BUTTON_CONFIRM = "✅ Підтвердити"
