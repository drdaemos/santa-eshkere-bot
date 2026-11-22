# 🎅 Санта Эщкере (Santa Eshkere) Bot

A Telegram bot for organizing company Secret Santa with exclusion rules (e.g., spouses won't be matched). Supports multiple groups with independent management.

## Features

- Multi-group support - bot can be activated in multiple Telegram groups
- Private registration via DM to keep wishlists secret
- Exclusion rules to prevent certain pairs from being matched
- Optional joining deadline
- Anonymous messages between each Santa and their receiver
- Secret Santa assignment algorithm with validation
- Admin commands for managing groups, rules, and participants
- All messages in Russian

## Quick Start

### 1. Create Your Bot

1. Talk to [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow the instructions
3. Save the bot token you receive

### 2. Install Dependencies

```bash
# Install uv if you don't have it
pip install uv

# Install project dependencies
uv sync
```

### 3. Configure Environment

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env and set TELEGRAM_BOT_TOKEN (from BotFather)
```

### 4. Run Database Migrations

```bash
# Apply database migrations
alembic upgrade head
```

### 5. Run the Bot

```bash
uv run python bot.py
```

The bot will start in polling mode using SQLite database for local development.

## Usage

### For Group Admins

1. **Activate the bot in your group:**
   - Add the bot to your Telegram group. When an admin adds it, the season
     opens right away and the bot posts the **join post**: a "🎁 Участвовать"
     button and the live list of who is in. Pin it if you like. (Added by a
     non-admin, it only says hello and asks an admin to send `/start`.)
   - `/start` in the group (admin only) does the same by hand; sent again, it
     re-posts the join post at the bottom of the chat.

2. **Manage from DM:**
   - With a single group there is nothing to select: commands act on it.
   - With several, `/listgroups` and tap one (or `/selectgroup 1`).
   - `/listjoined` shows who is in, who started registering but didn't finish,
     and (after the draw) whom the bot couldn't reach.
   - Send `/adminhelp` for all admin commands

3. **Set exclusion rules (optional):**
   - Send `/addrule` in DM
   - Follow the prompts to add pairs who shouldn't be matched

4. **Joining deadline (optional):**
   - `/deadline 30.11 18:00` in the group (a date alone means 23:59 that
     day; `/deadline off` removes it, `/deadline` shows it). Times are in
     `TIMEZONE` (default Europe/Moscow). The join post shows it.
   - From then on nobody new can start registering; people midway may finish.
     The join post loses its button, and the admin who set the deadline gets a
     DM with the count and who hasn't finished (in the group if they never
     opened the bot). Setting a later date reopens joining.

5. **Start Secret Santa:**
   - Once users have joined, send `/kickitoff` in the group. The bot asks
     first ("Запустить для 7 участников?") and names anyone still midway
     through registering; nothing is drawn until an admin taps "🎅 Запустить".
   - The prompt turns into "Сани поехали" and everyone gets a DM.

### For Participants

Participants never need a command:

1. **Join:** tap "🎁 Участвовать" on the join post. It opens the DM with the
   bot (Telegram shows a Start button the first time). Pick the name with one
   tap (Telegram name, or last season's) or type one, then send a wishlist.
   `/join` in the group still works. Tapping again or sending `/join` (in the
   group or to the bot) halfway through continues where the person stopped.
2. **Change the wishlist:** just send more ideas to the bot and tap
   "➕ Добавить": text is added to the end, so nothing typed earlier is
   lost. Replacing the whole list is a separate button ("🔁 Заменить", or
   "🔁 Заменить всё" under "✏️ Вишлист" / `/wishlist`). Every change shows
   the result with "↩️ Вернуть", which undoes the latest change once. After the draw
   the Santa is told what was added (or gets the new list).
3. **Check status:** `/status`, or tap the join button again.
4. **Leave:** the "🚪 Выйти" button (or `/leave`).
5. **Ask or answer anonymously:** after the draw, the assignment DM and
   `/status` have "✉️ Получателю" and "✉️ Санте".
   One tap, one text message, relayed by the bot; the other side gets it with
   a "↩️ Ответить" button. The receiver only ever sees "Тайный Санта"; the
   Santa sees the receiver's name (they know it anyway). Buttons of a pairing
   that changed (someone left, the draw was reset, a new season) stop working,
   and the bot logs neither the text nor who wrote to whom.

Design rules behind this:
- **Quiet group:** joining, leaving and changes after the draw only edit the
  join post. The bot posts in the group just for `/kickitoff` and when it
  can't reach someone by DM.
- **Hard to get wrong:** answered prompts lose their buttons, old buttons are
  harmless, text sent outside a step is offered as a wishlist (small talk
  isn't), and a forwarded join link only works for members of the group.
- Typing `/` shows a short command menu per chat type (DM, group, group admins).

### Changes after the draw

People have usually started shopping by then, so the bot never reshuffles
everyone:
- **Someone leaves** (`/leave`, or an admin's `/removeparticipant`): their
  Santa now gives to the leaver's receiver. If a rule forbids that pair, one
  more pair is rewired, so at most two Santas get a new assignment. If no such
  small fix exists, or fewer than 3 people would remain, the bot refuses and
  points to `/reset`.
- **Someone joins late** (`/join` works after the draw): one link A → B
  becomes A → newcomer → B. A gets a new assignment and the newcomer gets B.
- Only Santas whose assignment changed get a DM. The group sees who left,
  never who gives to whom.

## Admin Commands

Admins are the Telegram admins of each group; rights are re-checked with
Telegram on every command and button press.

### In Group Chat
- `/start` - Activate bot (admin only); opens a season if none is running
- `/kickitoff` - Draw and send assignments after a confirmation (admin only; refuses to reshuffle a drawn season)
- `/deadline 30.11 18:00` - Joining deadline (admin only; `/deadline off` removes it)
- `/newseason` - Close the current season and open a new one (admin only, asks to confirm)

### In DM with Bot
- `/listgroups` - List all active groups
- `/selectgroup <number>` - Select a group for management (or tap its button in `/listgroups`; not needed with one group)
- `/addrule` - Add exclusion rule
- `/listrules` - Show exclusion rules
- `/removerule` - Remove an exclusion rule
- `/listjoined` - Participants, unfinished registrations, undelivered assignments
- `/removeparticipant` - Remove someone from the season (repairs the draw)
- `/disband` - Deactivate the selected group
- `/dryrunassignments` - Check a draw is possible with the current rules (pairs are never shown)
- `/reset` - Clear this season's assignments (caution!)
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
   - `USE_WEBHOOK` - set to `true`
   - `DATABASE_URL` - reference the Postgres service's `DATABASE_URL`
   - `TIMEZONE` (optional) - IANA zone deadlines are typed and shown in, default `Europe/Moscow`
5. Build, start and healthcheck settings come from [railway.toml](railway.toml):
   migrations run as the pre-deploy step, and Railway only switches traffic to
   a new deploy once `GET /health` answers 200 (bot started, webhook set,
   database reachable).

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
│   ├── web.py               # Webhook + /health HTTP server (webhook mode)
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
- `groups` - Telegram groups where the bot is activated
- `events` - seasons per group: `open` -> `drawn` -> `closed` (one current season per group)
- `participants` - people in one season (every season starts empty; returning
  players can reuse last season's name and wishlist in one tap)
- `exclusions` - "never pair these two", per group, keyed by Telegram user id,
  so they carry over between seasons
- `assignments` - giver -> receiver within a season
- `dm_states` - pending DM conversation step and selected admin group (in the
  DB so a redeploy never loses someone mid-registration)

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

### An admin doesn't see their group (supergroups)

- Telegram only guarantees a bot can look up other members when the bot is
  an admin of the chat. In a supergroup (basic groups turn into one when, for
  example, an admin is promoted) that lookup can fail. The bot then checks
  the group's admin list instead, but the reliable fix is to **make the bot an
  admin of the group** (no special rights needed).
- Look for "Admin check in chat_id=… failed" in the logs.

### Can't send DM to users

- Telegram only lets a bot DM people who opened a chat with it. On `/join`
  the bot replies in the group with a button that opens the DM and resumes
  registration.
- After `/kickitoff` the group gets a list of anyone who could not be reached;
  they can open the bot and use `/status` to see their assignment.

### Assignment generation fails

- Check that you have at least 3 participants
- Too many exclusion rules can make assignment impossible
- Use `/reset` to clear assignments and try again

### Database errors

- Check `DATABASE_URL` is set correctly
- For Railway, ensure PostgreSQL plugin is added

## Testing

Everything runs against a **fake Telegram**: `tests/harness/fake_bot_api.py`
models users, chats and memberships and enforces the server rules real users
trip over: Markdown/HTML entity parsing, the 4096-char limit, "bot can't
initiate conversation", blocked users, "message is not modified", 64-byte
callback data. Scenarios read like chat transcripts:

```python
await alice.send(office, "/join")
await alice.dm("Алиса")
await admin.click(admin.last_dm, "Алиса")
await world.harness.restart()
```

Two layers share that DSL:

| Layer | Where | What it proves |
|---|---|---|
| in-process (`tests/flows`, most tests) | real `Application`, fake HTTP transport | every flow and edge case, fast (~25 s for ~290 tests) |
| process e2e (`tests/e2e`, marker `e2e`) | `bot.py` as its own OS process, talking HTTP to `tests/harness/server.py` | deploy-shaped startup (pre-deploy command from `railway.toml`, env-only config), polling and webhook modes, webhook secret enforcement, the `/health` endpoint Railway checks, surviving a killed process |

```bash
uv run pytest                 # everything on SQLite (~60 s)
uv run pytest -m "not e2e"    # fast loop
uv run pytest -m e2e          # just the process-level journeys
```

**Against Postgres** (what production runs, including the migration's
Postgres-only branch). Without Docker, start a throwaway server:

```bash
uv run --no-project --python 3.12 --with pgserver scripts/local_postgres.py
```

then run the suite with the printed `TEST_DATABASE_URL=...` set. The test
database is wiped per test, so never point it at real data.

CI (`.github/workflows/tests.yml`) runs lint and the full suite on SQLite and
on Postgres 17 for every push (any branch) and every PR.

Tests marked `known_bug` are strict xfails for reproduced-but-unfixed bugs;
when a fix makes one pass, the run fails until the marker is removed.

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
