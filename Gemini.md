1. Мета

Реалізувати стабільного WhatsApp-бота для групи, який:

веде список чергувань
автоматично оголошує чергового
нагадує про завершення чергування
фіксує порушення
працює тільки в дні чергування (Пн–Сб)
2. Технології
Python 3.11+
бібліотека: neonize
WhatsApp Web (whatsmeow)
SQLite (session.db)
JSON
Docker
3. Session (КРИТИЧНО)
session.db — обов'язковий
файл містить:
авторизацію
ключі
контакти
Вимоги:
зберігається на диску (volume)
НЕ пересоздається при рестарті контейнера
якщо відсутній → QR login
4. Архітектура
WhatsApp client (NewClient)
Event handlers
Scheduler (time-based jobs)
Storage (JSON)
Business logic
5. Дані
duty_list.json
{
  "queue": ["380XXXXXXXXX"]
}
guilty.json
{
  "records": []
}
runtime_state.json
{
  "current_duty": null,
  "last_rotation_date": null,
  "confirmed_today": false
}
6. JID (КРИТИЧНО)
chat_jid = f"{chat.User}@{chat.Server}"
sender_jid = f"{sender.User}@{sender.Server}"

❗ Заборонено .ToJID()

7. Типи чатів
if chat.Server == "g.us":
8. Команди
/add — додати в чергу
/list — список
/guilty — порушники
/done — завершив чергування
9. Чергування
ДНІ РОБОТИ

✅ Понеділок – Субота
❌ Неділя — ВИХІДНИЙ

Поведінка у неділю:
бот НЕ:
призначає чергового
не шле нагадування
не веде guilty
опціонально:
може писати: "Сьогодні вихідний"
10. Scheduler

Timezone: Europe/Kyiv

08:00 (Пн–Сб)
якщо не неділя:
визначити чергового
записати в state
відправити повідомлення
тегнути
PIN повідомлення
14:00
якщо не неділя
якщо confirmed_today == false:
нагадування
тег
17:30
повтор якщо не підтверджено
23:59
якщо не неділя:
якщо НЕ підтверджено:
запис у guilty.json
прокрутка черги
reset state
11. Відмітка
/done
тільки для поточного чергового
ставить confirmed_today = true
12. Mentions
@380XXXXXXXXX
mentions=[sender]
13. History Sync
ігнор перші 10–15 секунд після запуску
14. Anti-loop
if sender_jid == client_jid:
    return
15. Надійність
try/except всюди
reconnect
логування
не падати при помилках
16. Підключення
client.connect(block=False)
17. Docker
ВАЖЛИВО

session.db має зберігатись поза контейнером

Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir neonize pytz

CMD ["python", "main.py"]
docker-compose.yml
version: '3.9'

services:
  bot:
    build: .
    volumes:
      - ./data:/app
    restart: always
18. Структура
/app
 ├── main.py
 ├── session.db
 ├── duty_list.json
 ├── guilty.json
 ├── runtime_state.json
19. Edge cases
дублікати
пусті повідомлення
reconnect
відсутній session.db
неділя
20. Очікувана поведінка
стабільний бот
працює 24/7
не губить сесію
не працює у неділю
правильно веде чергу
21. Definition of Done
бот переживає рестарт контейнера
session.db збережений
чергування тільки Пн–Сб
guilty працює
команди працюють

---

## 22. HISTORY & REFACTORING PROMPT (FOR SENIOR AI)

### Історія проблем (Context for refactoring):
1. **Persistence:** Файли JSON іноді не синхронізуються або перезаписуються старими даними при рестарті. Потрібен надійний механізм збереження стану.
2. **Session Persistence:** `session.db` (SQLite) має бути в volume, інакше вилітає авторизація.
3. **Protobuf/Neonize:** При переписі обов'язково врахувати, що `neonize.proto.waE2E` та інші вкладені модулі потребують правильних імпортів та наявності `protobuf` в залежностях.
4. **Docker Env:** Необхідні системні бібліотеки `libmagic1` та `sqlite3` для коректної роботи `neonize`.
5. **JID handling:** Використання f-strings для JID замість `.ToJID()`.
6. **Reliability:** Потрібні чіткі тайм-аути та реконекти.

### prompt for Gemini (Senior Developer Role):
> "Перепиши цей проект як Senior Python Developer. 
> **Вимоги до коду:**
> 1. **Data Consistency:** Перейди з багатьох JSON-файлів на єдиний підхід (можливо `pydantic` моделі для валідації + один JSON/SQLite). Виріши проблему 'фантомних даних' (коли дані видалено, але бот їх бачить або повертає старі). Команду `/reg` заміни на `/add`.
> 2. **Architecture:** Використовуй Dependency Injection для сервісів. Відокрем логіку `DutyManager` від `WhatsAppClient`.
> 3. **Error Handling:** Додай кастомні Exceptions, детальний logging (з ротацією) та retry-логіку для мережевих запитів.
> 4. **Typing:** Повна типізація (typing hints) всюди.
> 5. **Safety:** Реалізуй справді атомарний запис у файли (locks + temp files) та перевірку стану файлів перед читанням.
> 6. **Performance:** Оптимізуй роботу шедулера, щоб він не пропускав події при рестарті в критичні години.
> 7. **Dockerfile & Compose:** Оптимізуй для швидкості білду та прозорої роботи з volumes. Docker-compose повинен монтувати `/app/data` коректно.
> 8. **Testing Tools:** Реалізуй зручну зміну часу сповіщень (наприклад, через .env файл або окремий config), щоб під час тестування можна було швидко перевірити всі часові інтервали.
> 9. **Auto-Binding:** Додай можливість вказати `GROUP_JID` у файлі `.env` або конфігурації. Бот повинен автоматично підхоплювати цей ІД при запуску, щоб не було потреби щоразу вводити команду `/bind_group` вручну (хоча команду варто залишити для майбутніх змін).
> 10. **Concurrency & Thread-Safety:** Оскільки `neonize` працює на колбеках у різних потоках, забезпеч повну потокобезпечність (thread-safety) при роботі зі спільними даними та файлами.
> 11. **Log Rotation:** Налаштуй логування так, щоб воно не забивало диск. Використовуй `RotatingFileHandler` (наприклад, зберігати максимум 5 останніх лог-файлів по 10 МБ кожен).
> 12. **Localization (i18n):** Винеси всі текстові повідомлення бота (привітання, звіти, помилки) в окремий файл локалізації (наприклад, `messages.yaml`). В коді не має бути захардкоджений український текст — все повинно читатися через шаблонізатор.
> 
> **Стек:** Python 3.11, Neonize, APScheduler, Pydantic, Logging.
> 
> Код має бути 'production-ready', читабельним і легко розширюваним (наприклад, для додавання статистики чергувань у майбутньому)."