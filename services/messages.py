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
QUEUE_CLEARED = "🗑 Чергу очищено."
GUILTY_CLEARED = "🗑 Список шкодників очищено."

QUEUE_EMPTY = "Черга порожня."
QUEUE_HEADER = "Поточна черга:"

GUILTY_EMPTY = "Шкодників немає. 🎉"
GUILTY_HEADER = "Список шкодників:"

DUTY_CONFIRMED = "✅ Чергування підтверджено!"
DUTY_ALREADY_CONFIRMED = "Ви вже відчергували сьогодні."
NOT_YOUR_DUTY = "Ви не є черговим сьогодні."
SUNDAY_NO_DUTY = "Сьогодні неділя, вихідний."

# ── Admin ─────────────────────────────────────────────────
NOT_ADMIN = "🔒 Ця команда доступна лише адміністраторам."
RATE_LIMITED = "⏳ Забагато команд. Зачекайте трохи."
ADMINS_HEADER = "Адміністратори:"
NO_ADMINS_CONFIGURED = "Список адміністраторів не налаштований."
NO_CURRENT_DUTY = "Немає призначеного чергового."

# ── Help ──────────────────────────────────────────────────
HELP_HEADER = "Доступні команди:"
HELP_PUBLIC = [
    "/add — додати себе до черги",
    "/done — підтвердити чергування",
    "/list — черга (10 найближчих)",
    "/rat — донести на когось",
    "/help — ця довідка",
]

# ── Fun ───────────────────────────────────────────────────
RAT_MESSAGES = [
    "🐀 Увага! @{user} підозріло довго не чергував!",
    "🚨 Донос: @{user} ухиляється від чергувань!",
    "🕵️ Анонімне повідомлення: @{user} вдає що не бачить повідомлень!",
    "⚠️ Увага! @{user} можливо не хоче чергувати!",
]

SWAP_REQUEST = "🔄 Запит на обмін чергуванням надіслано..."
SWAP_DENIED = "❌ ...відхилено. Чергуй давай."
RAT_ADMIN_PROTECTED = "🛡 На адміністраторів доносити не можна. Вони і так все знають."
HELP_ADMIN = [
    "Команди адміна:",
    "/add <номер> — додати когось (можна кілька)",
    "/remove <номер> — видалити з черги",
    "/remove-q — очистити чергу",
    "/remove-g — очистити список шкодників",
    "/guilty — список шкодників (з лічильником)",
    "/longlist — повна черга",
    "/trigger — нагадати черговому вручну",
    "/bind_group — прив'язати групу (робиться 1 раз)",
]

