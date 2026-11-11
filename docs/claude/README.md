# Sidequest — Claude docs (start here)

This folder is the working memory for Claude Code sessions building Sidequest.
It is split into small files so a session only loads what it needs.

## Every session, in this order

1. `README.md` (this file)
2. `BRIEF.md` — what we're building, constraints, decisions, architecture
3. `WORKFLOW.md` — how to work: model routing, git rules, context budget
4. `PROGRESS.md` — which segment is current, handoff notes from the last session
5. **Only** the current segment doc in `segments/`

Do not read other segment docs unless the current one tells you to (each lists
the interfaces it needs from earlier segments).

## File map

| File | Purpose |
|---|---|
| `BRIEF.md` | Product spec, hard constraints, decision log, architecture, assumptions |
| `WORKFLOW.md` | Rules for Claude: sessions, models, git, docs, conventions, testing |
| `PROGRESS.md` | Status per segment + handoff log |
| `RUNBOOK.md` | Operating the bot on the Pi: setup, config, deploy, health, backups, restore, upgrades |
| `segments/S1-foundation.md` | Repo skeleton, packaging, Docker, Postgres, CLI, update script, bot that connects |
| `segments/S2-data-model.md` | Schema, SQLAlchemy models, Alembic, DB test harness |
| `segments/S3-time-and-recurrence.md` | Pure time parsing, timezones, recurrence engine, Discord timestamp helpers |
| `segments/S4-services.md` | Domain services + permissions (Discord-free, reused by future web frontend) |
| `segments/S5-commands.md` | Slash commands, autocomplete, modals, list/upcoming views |
| `segments/S6-reminders.md` | Scheduler loop, reminder messages, Done button, DMs |
| `segments/S7-ops-and-hardening.md` | Health, backups, retention, runbook, final review |

## Kick-off prompt (for Tim)

> Read `docs/claude/README.md` and follow it. Start the segment that `PROGRESS.md` marks as next.

Between segments: review the diff, commit it yourself, then `/clear` and use the kick-off prompt again.
