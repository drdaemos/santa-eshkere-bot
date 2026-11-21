# 🎅 Санта Эщкере (Santa Eshkere) Bot

A Telegram bot for organizing company Secret Santa with exclusion rules (e.g., spouses won't be matched). Supports multiple groups with independent management.

## Features

- Multi-group support - bot can be activated in multiple Telegram groups
- Private registration via DM to keep wishlists secret
- Exclusion rules to prevent certain pairs from being matched
- Secret Santa assignment algorithm with validation
- Admin commands for managing groups, rules, and participants
- All messages in Russian

## Quick Start

### 1. Create Your Bot

1. Talk to [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow the instructions
3. Save the bot token you receive

### 2. Get Your Telegram ID

1. Talk to [@userinfobot](https://t.me/userinfobot) on Telegram
2. Send any message and it will reply with your user ID
3. Save this ID - you'll need it as the admin ID

### 3. Install Dependencies

```bash
# Install uv if you don't have it
pip install uv

# Install project dependencies
uv sync
```

### 4. Configure Environment

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env and add your values:
# - TELEGRAM_BOT_TOKEN (from BotFather)
# - ADMIN_TELEGRAM_ID (from userinfobot)
```

### 5. Run Database Migrations

```bash
# Apply database migrations
alembic upgrade head
```

### 6. Run the Bot

```bash
uv run python bot.py
```

The bot will start in polling mode using SQLite database for local development.

## Usage

### For Group Admins

1. **Activate the bot in your group:**
   - Add the bot to your Telegram group
   - Send `/start` in the group (admin only)

2. **Manage from DM:**
   - Send `/listgroups` to see all active groups
   - Send `/selectgroup 1` to select a group
   - Send `/adminhelp` for all admin commands

3. **Set exclusion rules (optional):**
   - Send `/addrule` in DM
   - Follow the prompts to add pairs who shouldn't be matched

4. **Start Secret Santa:**
   - Once users have joined, send `/kickitoff` in the group
   - Bot will generate assignments and DM each participant

### For Participants

1. **Join:**
   - Send `/join` in the group chat
   - Bot will DM you to collect your name and wishlist

2. **Update wishlist:**
   - Send `/wishlist` in DM with the bot

3. **Check status:**
   - Send `/status` in DM to see your registration and assignment

## Admin Commands

### In Group Chat
- `/start` - Activate bot (admin only)
- `/kickitoff` - Generate and send assignments (admin only)

### In DM with Bot
- `/listgroups` - List all active groups
- `/selectgroup <number>` - Select a group for management
- `/addrule` - Add exclusion rule
- `/listrules` - Show exclusion rules
- `/removerule` - Remove an exclusion rule
- `/listjoined` - Show all participants
- `/disband` - Deactivate the selected group
- `/reset` - Clear assignments (caution!)
- `/adminhelp` - Show all commands

## Deployment to Railway

### 1. Push to GitHub

```bash
git add .
git commit -m "Initial commit"
git push origin main
```

### 2. Deploy to Railway

1. Go to [railway.app](https://railway.app)
2. Create new project from GitHub repo
3. Add PostgreSQL plugin
4. Add environment variables:
   - `TELEGRAM_BOT_TOKEN` - your bot token
   - `ADMIN_TELEGRAM_ID` - your Telegram ID
   - `USE_WEBHOOK` - set to `true`
   - `EVENT_YEAR` - current year (e.g., 2024)
5. Configure build settings:
   - **Build Command:** `uv sync`
   - **Start Command:** `alembic upgrade head && uv run python bot.py`
6. Railway will automatically set `DATABASE_URL`, `PORT`, and provide a public URL

### 3. Set Webhook URL

After Railway deploys your app:
1. Copy your Railway app URL (e.g., `https://your-app.railway.app`)
2. Add environment variable: `WEBHOOK_URL=https://your-app.railway.app`
3. Redeploy

## Project Structure

```
santa-eshkere-bot/
├── src/
│   ├── __init__.py
│   ├── __main__.py          # Allows python -m src
│   ├── main.py              # Entry point
│   ├── config.py            # Configuration
│   ├── messages.py          # Russian messages
│   ├── database/
│   │   ├── models.py        # SQLAlchemy models
│   │   └── session.py       # DB session management
│   ├── handlers/
│   │   ├── group.py         # Group commands
│   │   ├── admin.py         # Admin commands
│   │   └── user.py          # User DM flow
│   ├── services/
│   │   ├── assignment.py    # Assignment algorithm
│   │   └── notifications.py # DM notifications
│   └── utils/
│       └── auth.py          # Authentication
├── alembic/
│   ├── versions/            # Database migration files
│   ├── env.py               # Alembic environment config
│   └── script.py.mako       # Migration template
├── bot.py                   # Simple entry script
├── alembic.ini              # Alembic configuration
├── Dockerfile
├── .env.example
├── pyproject.toml
└── README.md
```

## Database

- **Development:** SQLite (automatic, no setup needed)
- **Production:** PostgreSQL (Railway provides this automatically)

Tables:
- `groups` - Telegram groups where bot is activated
- `users` - Participants in each group
- `exclusions` - Rules for who can't be matched together
- `assignments` - Secret Santa assignments by year

### Database Migrations

This project uses Alembic for database migrations.

**Important:** Run migrations before starting the bot:
```bash
alembic upgrade head
```

#### Creating New Migrations

When you modify the database models in `src/database/models.py`, create a new migration:

```bash
# Generate a new migration based on model changes
alembic revision --autogenerate -m "Description of changes"

# Review the generated migration in alembic/versions/
# Edit if needed, then apply it with:
alembic upgrade head
```

#### Migration Commands

```bash
# Apply all pending migrations
alembic upgrade head

# Rollback the last migration
alembic downgrade -1

# Show current migration status
alembic current

# Show migration history
alembic history
```

## Troubleshooting

### Bot doesn't respond to commands

- Make sure you've set `TELEGRAM_BOT_TOKEN` correctly
- Check that the bot is running (look for "Starting bot..." in logs)
- For group commands, ensure you're an admin

### Can't send DM to users

- Users must start a conversation with the bot first
- Tell users to search for your bot and send `/start` before joining

### Assignment generation fails

- Check that you have at least 3 participants
- Too many exclusion rules can make assignment impossible
- Use `/reset` to clear assignments and try again

### Database errors

- Check `DATABASE_URL` is set correctly
- For Railway, ensure PostgreSQL plugin is added

## Testing

The suite drives the real `Application` (handlers, filters, routing) through an
in-process fake Telegram Bot API (`tests/harness/`). The fake enforces the
server rules real users trip over: Markdown/HTML entity parsing, the 4096-char
limit, "bot can't initiate conversation", "message is not modified", 64-byte
callback data. Scenarios read like chat transcripts (`alice.send(group, "/join")`,
`admin.click(msg, "Алиса")`, `harness.restart()` to simulate a redeploy).

Tests marked `known_bug` are strict xfails documenting current real-usage
failures. When a fix makes one pass, the run fails until the marker is removed.

```bash
uv run pytest                      # SQLite, fresh DB per test, built via Alembic
uv run pytest -m known_bug -rx     # list the documented failures
TEST_DATABASE_URL=postgresql://... uv run pytest   # disposable Postgres (wiped per test)
```

On Windows set `PYTHONUTF8=1` if you print Russian text from tests.

## Development

```bash
# Run in development mode
uv run python bot.py

# Run tests
uv run pytest

# Format code
uv run black src/

# Lint code
uv run ruff check src/

# Create a new database migration after modifying models
alembic revision --autogenerate -m "Description of changes"

# Apply migrations
alembic upgrade head
```

## License

MIT

## Support

For issues and questions, please check the spec document or create an issue in the repository.
