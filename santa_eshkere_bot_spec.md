# Санта Эщкере (Santa Eshkere) Telegram Bot - Implementation Specification

## Overview
A Telegram bot "Санта Эщкере" for organizing company Secret Santa with exclusion rules (e.g., spouses won't be matched). Bot operates in a group for discovery, with private DMs for sensitive interactions. All user-facing text is in Russian.

## Technical Stack
- **Language**: Python 3.12+
- **Bot Framework**: python-telegram-bot (latest stable, webhook mode)
- **Database**: PostgreSQL
- **ORM**: SQLAlchemy (async)
- **Dependency Management**: uv
- **Deployment**: Railway (auto-build Docker container)
- **Project Structure**: Proper Python project with modular structure

## Database Schema

### groups table
```sql
CREATE TABLE groups (
    id SERIAL PRIMARY KEY,
    telegram_chat_id BIGINT UNIQUE NOT NULL,
    group_name TEXT,
    activated_at TIMESTAMP DEFAULT NOW(),
    disbanded_at TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_groups_telegram_chat_id ON groups(telegram_chat_id);
CREATE INDEX idx_groups_is_active ON groups(is_active);
```

### users table
```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL,
    telegram_username TEXT,
    real_name TEXT NOT NULL,
    wishlist TEXT,
    group_id INTEGER REFERENCES groups(id) ON DELETE CASCADE,
    joined_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(telegram_id, group_id)  -- Same user can join multiple groups
);

CREATE INDEX idx_users_telegram_id ON users(telegram_id);
CREATE INDEX idx_users_group_id ON users(group_id);
```

### exclusions table
```sql
CREATE TABLE exclusions (
    id SERIAL PRIMARY KEY,
    user1_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    user2_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    group_id INTEGER REFERENCES groups(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user1_id, user2_id, group_id),
    CHECK(user1_id < user2_id)  -- Ensure canonical ordering
);

CREATE INDEX idx_exclusions_group_id ON exclusions(group_id);
```

### assignments table
```sql
CREATE TABLE assignments (
    id SERIAL PRIMARY KEY,
    group_id INTEGER REFERENCES groups(id) ON DELETE CASCADE,
    event_year INTEGER NOT NULL,
    giver_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    receiver_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    assigned_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(group_id, event_year, giver_id)
);

CREATE INDEX idx_assignments_group_id ON assignments(group_id);
CREATE INDEX idx_assignments_event_year ON assignments(event_year);
```

## Bot Commands & Flows

### Group Commands

#### `/start` (Admin only, in group)
- Activates bot in the group
- Creates/reactivates group record in database
- Stores group chat ID and name for this Secret Santa event
- Bot posts welcome message in Russian:
  ```
  🎅 Санта Эщкере активирован!
  
  Чтобы участвовать, напишите /join
  Бот отправит вам личное сообщение для регистрации.
  ```
- If group was previously disbanded, reactivates it

#### `/join` (Any user, in group)
- **Visible in group**: User types `/join`
- **Bot checks**: Group must be active (not disbanded)
- **Bot action**: 
  - Associates user registration with this specific group
  - Sends DM to user with instructions
  - No group response (silent) OR optional generic "Check your DM!"

#### `/kickitoff` (Admin only, in group)
- Triggers assignment generation for this specific group
- Bot validates:
  - At least 3 participants joined in this group
  - Valid assignment possible given exclusion rules for this group
- Sends DM to each participant with their assignment
- Posts confirmation in group: "🎅 Распределение отправлено! Проверьте личные сообщения"

### Admin DM Commands

#### `/listgroups`
- Shows all groups where bot is active
- Format:
  ```
  Активные группы:
  1. Рабочая команда (ID: -1001234567890)
     • Активирована: 2024-12-01
     • Участников: 12
     • Распределение: Отправлено
  
  2. Друзья (ID: -1009876543210)
     • Активирована: 2024-12-10
     • Участников: 5
     • Распределение: Не отправлено
  
  Используйте /selectgroup <номер> для выбора группы
  ```

#### `/selectgroup <number>`
- Selects active group for subsequent admin commands
- Remembers selection for the admin's session
- Example: `/selectgroup 1`
- Confirms: "✓ Выбрана группа: [Название]"
- All subsequent `/addrule`, `/listrules`, `/listjoined`, `/reset` commands apply to selected group

#### `/disband`
- Disbands the currently selected group
- Asks for confirmation: "Это отметит группу [Название] как расформированную. Пользователи не смогут присоединиться. Продолжить? (да/нет)"
- Sets `is_active = FALSE` and `disbanded_at = NOW()`
- Does NOT delete data (preserves history)
- Confirms: "✓ Группа расформирована. Используйте /start в той группе для повторной активации."

#### `/addrule`
- Works on currently selected group
- Sends message with RequestUser button: "Выберите первого человека"
- **Important**: RequestUser only shows users from the selected group's participants
- After first selection, shows: "Выбран [Имя]. Выберите второго человека"
- After second selection, confirms via DM: "✓ Правило исключения добавлено для [Название группы]: [Имя1] ↔ [Имя2]"
- No group notification (keeps rules private)

#### `/listrules`
- Shows all current exclusion pairs for selected group in DM
- Format:
  ```
  Правила исключения для [Название группы]:
  • Алиса ↔ Боб
  • Чарли ↔ Диана
  
  Всего: 2 правила
  ```

#### `/removerule`
- Shows inline keyboard with all current exclusion pairs for selected group as buttons
- Admin clicks rule to remove
- Confirms deletion: "✓ Правило удалено"

#### `/listjoined`
- Shows all participants who completed registration for selected group
- Format:
  ```
  Зарегистрированные участники в [Название группы] (5):
  • Алиса (@alice)
  • Боб (@bob)
  • Чарли
  • Диана (@diana)
  • Евгений (@eugene)
  ```

#### `/adminhelp`
- Lists all admin commands with brief descriptions in Russian

#### `/reset` (Caution command)
- Clears all assignments for selected group's current year
- Asks for confirmation: "⚠️ Это удалит все распределения для этой группы. Продолжить? (да/нет)"
- Does NOT clear participants or exclusions
- Confirms: "✓ Распределения сброшены"

### User DM Flow (Triggered by `/join`)

**Step 1: Initial DM**
```
🎅 Добро пожаловать в Санта Эщкере для [Название группы]!

Давайте зарегистрируем вас. Сначала, как вас зовут? 
(Это имя увидит ваш Санта Эщкере)
```

**Step 2: Name confirmation**
User sends: "Евгений"
Bot responds:
```
Отлично! Теперь напишите ваш вишлист.

Будьте конкретны! Укажите:
• Идеи подарков
• Интересы/хобби
• Размеры одежды
• Что вы НЕ хотите

Вы сможете изменить это позже командой /wishlist
```

**Step 3: Wishlist submission**
User sends: "Люблю настольные игры, кофе, размер одежды L..."
Bot responds:
```
✓ Всё готово!

Имя: Евгений
Вишлист: Люблю настольные игры, кофе...

Вы получите сообщение, когда администратор отправит распределение.

Доступные команды:
/wishlist - Изменить вишлист
/status - Посмотреть статус регистрации
```

### User DM Commands

#### `/wishlist`
- Shows current wishlist: "Ваш текущий вишлист: [текст]"
- Prompts for new wishlist text: "Напишите новый вишлист:"
- Updates database
- Confirms update: "✓ Вишлист обновлён!"

#### `/status`
- Before assignment:
  ```
  ✓ Вы зарегистрированы в [Название группы]!
  
  Имя: Евгений
  Вишлист: Люблю настольные игры...
  
  Ожидаем распределения от администратора.
  ```
  
- After assignment:
  ```
  ✓ Вы зарегистрированы в [Название группы]!
  🎁 Ваше распределение Санта Эщкере:
  
  Имя: Алиса
  Вишлист: Книги, чай, растения...
  
  Удачи! 🎅
  ```
  
- If registered in multiple groups:
  ```
  Вы зарегистрированы в нескольких группах:
  
  1. Рабочая команда
     Статус: Распределено (дарите Алисе)
  
  2. Друзья
     Статус: Ожидание распределения
  ```

## Assignment Algorithm

### Requirements
- Each person gives to exactly one person
- Each person receives from exactly one person
- No self-assignments
- Respects exclusion rules (bidirectional)
- Deterministic but randomized

### Implementation Approach

```python
def generate_assignments(participants: List[User], exclusions: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """
    Generate Secret Santa assignments.
    
    Returns list of (giver_id, receiver_id) tuples.
    Raises exception if no valid assignment exists.
    """
    n = len(participants)
    
    # Build forbidden pairs set (bidirectional + self)
    forbidden = set()
    for user_id in participants:
        forbidden.add((user_id, user_id))  # No self-assignment
    
    for (id1, id2) in exclusions:
        forbidden.add((id1, id2))
        forbidden.add((id2, id1))
    
    # Try random derangements until valid one found
    import random
    max_attempts = 10000
    
    for attempt in range(max_attempts):
        receivers = participants.copy()
        random.shuffle(receivers)
        
        valid = True
        for giver, receiver in zip(participants, receivers):
            if (giver, receiver) in forbidden:
                valid = False
                break
        
        if valid:
            return list(zip(participants, receivers))
    
    raise ValueError(f"No valid assignment found after {max_attempts} attempts")
```

### Edge Cases
- Too many exclusions (impossible to assign)
- Odd exclusion patterns creating isolated groups
- Small participant count (<3)

Bot should validate and report specific error to admin if assignment fails.

## Privacy & Security Requirements

### Message Privacy
1. All wishlist data only visible in DMs
2. Assignments only sent via DM
3. Exclusion rules never posted in group
4. `/addrule` confirmation sent to admin DM only

### Admin Authentication
- Hardcode admin Telegram ID in environment variable
- All admin commands check `message.from_user.id == ADMIN_ID`
- Reject admin commands from non-admin users silently

### Data Privacy
- Don't log wishlist content
- Don't log assignment pairs (except in DB)
- Sanitize error messages (no user data in exceptions)

## User Experience Details

### Message Formatting
- Use **bold** for names
- Use emoji for visual clarity (🎅 🎁 ✓ ❌)
- Keep messages concise
- Use Markdown formatting

### Error Handling

**User errors:**
- "❌ Вы уже зарегистрированы в этой группе! Используйте /wishlist для изменения."
- "❌ Эта группа неактивна. Попросите администратора активировать её командой /start."
- "❌ Сначала нужно зарегистрироваться. Напишите /join в группе."
- "❌ Я могу общаться только в личных сообщениях. Нажмите сюда: [ссылка на бота]"

**Admin errors:**
- "❌ Только администратор может использовать эту команду."
- "❌ Пожалуйста, сначала выберите группу командой /selectgroup."
- "❌ Недостаточно участников в этой группе (минимум 3)."
- "❌ Невозможно создать корректное распределение с текущими правилами исключения."
- "❌ Группа не найдена или уже расформирована."

**System errors:**
- "⚠️ Что-то пошло не так. Попробуйте ещё раз или обратитесь к администратору."
- Log full error details server-side

### Admin Session State Management

Since admin needs to select a group before using group-specific commands, maintain in-memory state:

```python
# Use python-telegram-bot's context.user_data for persistence
async def select_group(update, context):
    context.user_data['selected_group_id'] = group_id
    
# Decorator to ensure group is selected
def require_selected_group(func):
    async def wrapper(update, context):
        if 'selected_group_id' not in context.user_data:
            await update.message.reply_text("❌ Пожалуйста, сначала выберите группу командой /selectgroup.")
            return
        return await func(update, context)
    return wrapper
```

**Note**: python-telegram-bot supports persistence backends (pickle, JSON, custom). Configure in application builder for session survival across restarts.

## Localization

All bot messages are in Russian with the bot name "Санта Эщкере" (Santa Eshkere). For code identifiers, use the anglicized form "santa_eshkere".

Organize messages in a separate module for maintainability:

```python
# src/santa_eshkere/messages.py

class Messages:
    # Group messages
    WELCOME = """🎅 Санта Эщкере активирован!

Чтобы участвовать, напишите /join
Бот отправит вам личное сообщение для регистрации."""
    
    ASSIGNMENTS_SENT = "🎅 Распределение отправлено! Проверьте личные сообщения"
    
    # User registration flow
    ASK_NAME = """🎅 Добро пожаловать в Санта Эщкере для {group_name}!

Давайте зарегистрируем вас. Сначала, как вас зовут? 
(Это имя увидит ваш Санта Эщкере)"""
    
    ASK_WISHLIST = """Отлично! Теперь напишите ваш вишлист.

Будьте конкретны! Укажите:
• Идеи подарков
• Интересы/хобби
• Размеры одежды
• Что вы НЕ хотите

Вы сможете изменить это позже командой /wishlist"""
    
    # ... other messages
```

### Assignment Notification

When admin triggers `/kickitoff`, each participant receives:

```
🎁 Ваше распределение Санта Эщкере!

Вы дарите подарок для:
👤 **Алиса**
📝 Вишлист:
Книги (фэнтези/фантастика), листовой чай, комнатные растения, туристическое снаряжение

💡 Совет: Если нужно уточнение, можете спросить в групповом чате (не раскрывая, что вы их Санта!)

Счастливого дарения! 🎅
```

## Configuration Requirements

### Environment Variables
```bash
TELEGRAM_BOT_TOKEN=<bot_token>
ADMIN_TELEGRAM_ID=<admin_user_id>
DATABASE_URL=postgresql://user:pass@localhost:5432/santa_eshkere
EVENT_YEAR=2024  # For multi-year support
WEBHOOK_URL=<https://your-app.railway.app/webhook>  # Railway provides this
PORT=8000  # Railway assigns this
```

### Database Connection
- Use asyncpg with SQLAlchemy async
- Connection pooling via SQLAlchemy engine
- Handle connection failures gracefully
- Retry logic for transient DB errors

## Deployment on Railway

### Project Structure
```
santa-eshkere-bot/
├── pyproject.toml           # uv project config
├── uv.lock
├── Dockerfile               # Railway auto-build
├── .dockerignore
├── run.sh                   # Entrypoint script
├── alembic.ini             # Database migrations
├── alembic/
│   ├── versions/
│   └── env.py
└── src/
    └── santa_eshkere/
        ├── __init__.py
        ├── main.py          # Entry point, webhook setup
        ├── config.py        # Environment variables
        ├── messages.py      # Russian message templates
        ├── database/
        │   ├── __init__.py
        │   ├── models.py    # SQLAlchemy models
        │   └── session.py   # DB session management
        ├── handlers/
        │   ├── __init__.py
        │   ├── group.py     # Group commands (/start, /join, /kickitoff)
        │   ├── admin.py     # Admin DM commands
        │   └── user.py      # User DM commands
        ├── services/
        │   ├── __init__.py
        │   ├── assignment.py    # Assignment generation logic
        │   └── notifications.py # DM sending
        └── utils/
            ├── __init__.py
            └── auth.py      # Admin auth helpers
```

### Dockerfile
```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Copy project files
COPY pyproject.toml uv.lock ./
COPY src/ ./src/
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY run.sh ./

# Install dependencies
RUN uv sync --frozen

# Make run script executable
RUN chmod +x run.sh

# Railway will set PORT
EXPOSE 8000

CMD ["./run.sh"]
```

### run.sh
```bash
#!/bin/bash
set -e

# Run migrations
uv run alembic upgrade head

# Start bot with webhook
uv run python -m santa_eshkere.main
```

### Webhook Setup (main.py)
```python
from telegram.ext import Application
import os

async def setup_webhook(application: Application):
    webhook_url = os.getenv("WEBHOOK_URL")
    port = int(os.getenv("PORT", 8000))
    
    await application.bot.set_webhook(
        url=f"{webhook_url}/webhook",
        allowed_updates=["message", "callback_query"]
    )
    
    # Railway handles HTTPS termination
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path="/webhook",
        webhook_url=f"{webhook_url}/webhook"
    )
```

### Railway Configuration
- Auto-detects Dockerfile
- Sets DATABASE_URL automatically if Postgres plugin added
- Provides RAILWAY_PUBLIC_DOMAIN for webhook URL
- Handles HTTPS/SSL automatically

## Logging & Monitoring

### Logging
- Log to stdout (Railway captures logs)
- Log levels: INFO for normal ops, DEBUG for development
- Log format: timestamp, level, message, context (group_id, user_id when relevant)
- Don't log sensitive data (wishlists, assignments)
- Sanitize error messages

### Health Check
- Implement `/health` endpoint for Railway
- Returns 200 OK if bot is running and can connect to DB

### Monitoring
- Railway provides automatic metrics
- Track bot uptime via webhook health
- Monitor message processing errors in logs
- Alert on database connection failures

## Testing Scenarios

### Happy Path
1. Admin starts bot in Group A
2. Admin selects Group A and adds exclusion rules
3. Users join Group A and set wishlists
4. Admin triggers assignment for Group A
5. All users receive valid assignments

### Multi-Group Scenarios
1. Admin starts bot in Group A and Group B
2. Same user joins both groups
3. Admin manages exclusions separately for each group
4. Admin assigns each group independently
5. User can see status for both groups via `/status`

### Edge Cases
1. User tries to join same group twice
2. User updates wishlist multiple times
3. Admin tries to add duplicate exclusion rule
4. Impossible assignment scenario (too many exclusions)
5. Admin disbands group, user tries to join
6. Admin reactivates disbanded group
7. Database connection lost during operation
8. User DMs bot before joining
9. Admin tries to use group-specific command without selecting group
10. Bot added to new group without `/start`

### Admin Workflows
1. List participants before assignment
2. Remove and re-add exclusion rules
3. Reset assignments and reassign
4. Handle users who join after assignments sent
5. Switch between multiple active groups
6. Disband and reactivate groups

## Future Enhancements (Out of Scope for V1)
- Multi-year history tracking
- Reminder system (1 week before event)
- Budget field in wishlist
- Photo upload support for wishlists
- Reveal feature (show who had whom after event)
- Statistics (participation rate over years)

## Implementation Notes

### SQLAlchemy Async Setup
```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

engine = create_async_engine(
    os.getenv("DATABASE_URL").replace("postgresql://", "postgresql+asyncpg://"),
    echo=False,
    pool_pre_ping=True
)

async_session = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)
```

### Alembic Migrations
- Use alembic for database schema management
- Auto-generate migrations from SQLAlchemy models
- Run migrations in run.sh before starting bot
- Keep migration history in version control

### python-telegram-bot Persistence
```python
from telegram.ext import Application, PicklePersistence

persistence = PicklePersistence(filepath="bot_data.pkl")

application = (
    Application.builder()
    .token(os.getenv("TELEGRAM_BOT_TOKEN"))
    .persistence(persistence)
    .build()
)
```

### RequestUser Button Implementation
```python
from telegram import KeyboardButton, KeyboardButtonRequestUsers

button = KeyboardButton(
    text="Select first person",
    request_users=KeyboardButtonRequestUsers(
        request_id=1,
        user_is_bot=False,
        max_quantity=1
    )
)
```

### Webhook Health Endpoint
```python
from aiohttp import web

async def health(request):
    # Check DB connection
    try:
        async with async_session() as session:
            await session.execute("SELECT 1")
        return web.Response(text="OK", status=200)
    except Exception as e:
        return web.Response(text=f"Error: {e}", status=500)

app.router.add_get('/health', health)
```

## Success Criteria

The bot is considered complete when:
- ✅ Bot can be activated in multiple groups independently
- ✅ Users can join and set wishlists via DM (group-specific)
- ✅ Admin can select and manage multiple groups from DM
- ✅ Admin can set exclusion rules privately per group
- ✅ Admin can disband and reactivate groups
- ✅ Valid assignments are generated respecting all constraints per group
- ✅ Assignments are delivered privately to participants
- ✅ All sensitive data remains private
- ✅ Bot handles errors gracefully
- ✅ Bot runs stably on Railway with webhooks
- ✅ Database migrations run automatically on deploy

---

**Total Estimated Lines of Code**: 1000-1400 lines (with multi-group support)
**Estimated Implementation Time**: 10-14 hours
**Complexity Level**: Medium-High

## pyproject.toml Template

```toml
[project]
name = "santa-eshkere-bot"
version = "0.1.0"
description = "Telegram bot 'Santa Eshkere' for organizing Secret Santa with exclusion rules"
requires-python = ">=3.12"
dependencies = [
    "python-telegram-bot[webhooks]>=21.0",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "python-dotenv>=1.0",
    "aiohttp>=3.9",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "black>=24.0",
    "ruff>=0.1",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
dev-dependencies = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]
```
