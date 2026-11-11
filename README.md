# Sidequest

A Discord bot for to-dos, written in Python, running in Docker on a Raspberry Pi.

Every server gets one shared to-do list, and every user gets a personal list that follows
them into every server and into DMs with the bot. Timed to-dos remind you at the right
moment: server reminders are posted in the server's reminder channel and ping the assignees,
personal reminders arrive as a DM.

## Features

- **Two lists:** a shared server list (with assignees) and a personal list per user.
- **One-time to-dos**, with or without a date and time (`HH:MM`, 24-hour).
- **Repeating to-dos:** daily, weekly (several days), monthly on a weekday ("first Sunday")
  or on a day of the month ("the 15th", "last day"), each with one or more times.
- **Subtasks** (up to 50 per to-do) and long multi-line **details**.
- **Reminders** with a **Done** button and subtask checkboxes; anyone who can see a server
  reminder can check it off. An unchecked reminder of a repeating to-do is replaced by the
  next one.
- **Timezones** per user (or per to-do). Times are shown as Discord timestamps, so everyone
  sees them in their own timezone.
- **Upcoming view** to check things off before they're due.
- Runs on a Pi: PostgreSQL in Docker, automatic backups on update, health check and
  automatic restart when stuck, optional cleanup of old history.

## Commands

| Command | What it does |
|---|---|
| `/todo add` | Add a one-time to-do (optionally with date/time, details, assignees) |
| `/todo repeat daily · weekly · monthly-weekday · monthly-day` | Add a repeating to-do |
| `/todo list` · `/todo show` · `/todo upcoming` | View the lists, one to-do, or what's coming up |
| `/todo done` · `/todo edit` · `/todo details` · `/todo assign` · `/todo delete` | Change a to-do |
| `/todo subtask add` · `/todo subtask remove` | Manage the checklist |
| `/settings timezone` | Set your timezone |
| `/sidequest channel` | Pick (or clear) the server's reminder channel (Manage Server) |
| `/sidequest about` | Version and deploy info |

Replies are only visible to you; `/todo list post:true` shares a server list with the
channel.

## Running it

See the **[runbook](docs/claude/RUNBOOK.md)**: Pi setup, Discord Developer Portal setup,
configuration, deploying with `update.sh`, backups and restore, logs, and upgrades.

Short version, on a 64-bit Raspberry Pi OS with Docker:

```sh
cp configs/.env.example configs/.env   # fill in the token and database password
./update.sh
```

## Development

Python 3.12, discord.py, SQLAlchemy (async) + PostgreSQL 17, Alembic, pydantic.
Dependencies are declared in `pyproject.toml` and compiled with
`scripts/compile-requirements.sh`.

```sh
ruff check . && ruff format --check .
docker compose -f compose.test.yaml up -d
TEST_DATABASE_URL=postgresql+asyncpg://sidequest:sidequest@localhost:55432/sidequest_test pytest
```

Design notes and decisions: [`docs/claude/BRIEF.md`](docs/claude/BRIEF.md).
