# Sidequest

A Discord bot for to-dos, written in Python, running in Docker on a Raspberry Pi.

A server can have several named to-do lists. Every server has a **Default List** that
everyone can use; anyone can make more lists and choose who may work on them. Timed to-dos
remind you at the right moment: reminders are posted in the server's reminder channel and
ping the assignees. Sidequest only works in servers (no DMs).

## Features

- **Named lists per server:** a Default List open to everyone, plus lists with an owner and
  collaborators (only they can change and check off its to-dos; everyone can see them).
  Everyone picks their own default list with `/settings default-list`.
- **One-time to-dos**, with or without a date and time (`HH:MM`, 24-hour).
- **Repeating to-dos:** daily, weekly (several days), monthly on a weekday ("first Sunday")
  or on a day of the month ("the 15th", "last day"), each with one or more times.
- **Subtasks** (up to 50 per to-do) and long multi-line **details**.
- **Reminders** with a **Done** button and subtask checkboxes; whoever may work on the list
  can check it off. An unchecked reminder of a repeating to-do is replaced by the next one.
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
| `/todo list` · `/todo show` · `/todo upcoming` | View a list, one to-do, or what's coming up |
| `/todo done` · `/todo edit` · `/todo details` · `/todo assign` · `/todo move` · `/todo delete` | Change a to-do |
| `/todo subtask add` · `/todo subtask remove` | Manage the checklist |
| `/lists create` · `/lists rename` · `/lists delete` · `/lists show` | Manage the server's lists |
| `/lists collaborators` · `/lists transfer` | Choose who may work on a list; give it a new owner |
| `/settings timezone` · `/settings default-list` | Set your timezone; pick your default list |
| `/sidequest channel` | Pick (or clear) the server's reminder channel (Manage Server) |
| `/sidequest about` | Version and deploy info |

Replies are only visible to you; `/todo list post:true` shares a list with the channel.

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
