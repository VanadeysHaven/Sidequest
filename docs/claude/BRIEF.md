# Sidequest — Project brief

> Owner: Tim. Written by Claude (Opus 5.5), 2026-11-10.
> This is the source of truth for *what* we build. `WORKFLOW.md` covers *how* Claude works.
> Change rules: new decisions are appended to §3 with a date. Existing decisions change only with Tim's approval.

---

## 1. What Sidequest is

A Discord bot for to-dos, written in Python, running in Docker on a Raspberry Pi.
It has two kinds of lists:

- **Server list** — one shared list per Discord server. To-dos can have assignees; reminders are posted in the server's reminder channel, pinging the assignees.
- **Personal list** — one per user, the same in every server and in DMs with the bot. Reminders arrive as a DM.

To-dos can be one-time (untimed, or timed with a date + time) or repeating (daily / weekly / monthly), can have a checklist of subtasks and optional long multi-line details. A web frontend will come later; it is **out of scope now**, but the design must leave room for it (§5.6).

---

## 2. Hard constraints (from Tim)

| # | Constraint |
|---|---|
| C1 | Backend in Python. |
| C2 | Runs in Discord; slash commands, no gateway intents (see D11 — this is feasible). |
| C3 | Runs on a Raspberry Pi in Docker (Docker Compose). |
| C4 | Times are **entered** in 24-hour format only (`HH:MM`). No am/pm parsing. |
| C5 | Every **point in time** the bot prints uses a Discord timestamp (`<t:unix:style>`). |
| C6 | Relational, lightweight database. **Not SQLite.** |
| C7 | Python requirements are compiled from `pyproject.toml` with `pip-compile` (pip-tools). |
| C8 | `sidequest` CLI command starts the bot. |
| C9 | An update script for the server (git pull, DB backup, `docker compose up --build`…). Template: `docs/examples/update-script.sh.example`. |
| C10 | Claude rules: segmented design; Haiku coders where sensible; may create branches, **never commit or push**, no worktrees; Claude docs live in `docs/claude/`; documentation is always written by Opus 5.5. |

---

## 3. Decision log

| ID | Date | Decision | Source |
|---|---|---|---|
| D1 | 2026-11-10 | Times are entered as 24h `HH:MM`. Points in time are shown as Discord timestamps, which Discord renders as 12h or 24h depending on each **viewer's** Discord language setting; that is accepted. Text that is *not* a point in time (e.g. "every Monday at 12:00") is written in 24h. | Tim |
| D2 | 2026-11-10 | One shared list per server **plus** one personal list per user. | Tim |
| D3 | 2026-11-10 | Anyone who can see a server reminder can check it off. Checking off completes it for everyone. | Tim |
| D4 | 2026-11-10 | Subtasks are simple checklist items (no own time/assignee). On repeating to-dos they reset for each new occurrence. | Tim |
| D5 | 2026-11-10 | The personal list is global (all servers + DMs with the bot). Personal reminders are sent as DMs. | Tim |
| D6 | 2026-11-10 | One reminder channel per server, set by an admin (Manage Server). All server reminders go there. | Tim |
| D7 | 2026-11-10 | Repeating to-do: when a new occurrence fires while the previous reminder is still unchecked, the old reminder is deleted and marked *missed*. At most one open reminder per repeating to-do. | Tim |
| D8 | 2026-11-10 | Completed to-dos are kept in the DB as history (hidden from lists). Optional retention cleanup later (S7). | Tim |
| D9 | 2026-11-10 | Every to-do can optionally carry long multi-line **details** text (≤ 4000 chars), entered via a Discord modal and shown in the reminder. | Tim |
| D10 | 2026-11-10 | Database: **PostgreSQL 17** (`postgres:17-alpine`, arm64 image). Matches the Postgres backup in Tim's update-script example. | Claude |
| D11 | 2026-11-10 | Gateway connection with `discord.Intents.none()`. Slash commands, buttons, selects, modals and autocomplete all arrive as interactions, which Discord delivers regardless of intents; posting, DMing and deleting messages are plain REST calls. No public HTTP endpoint needed on the Pi. | Claude |
| D12 | 2026-11-10 | Library: **discord.py 2.7.x** (`app_commands`, `ui.DynamicItem` for restart-proof buttons). | Claude |
| D13 | 2026-11-10 | SQLAlchemy 2.x (async) + asyncpg + Alembic migrations. | Claude |
| D14 | 2026-11-10 | The DB is the single source of truth for schedules. The scheduler polls the DB (sleep until next due, capped at 60 s) and can be woken in-process. No in-memory job store. | Claude |
| D15 | 2026-11-10 | Recurrence engine is hand-written and pure (zoneinfo only, no `dateutil.rrule`), heavily table-tested. | Claude |
| D16 | 2026-11-10 | ~~Python 3.13, `python:3.13-slim` base image.~~ Superseded by D31. | Claude |
| D17 | 2026-11-10 | One-time to-dos are either **untimed** (no date, no time) or **timed** (date + time). A date without a time is rejected. (was A1) | Tim |
| D18 | 2026-11-10 | When entering a timed to-do the date may be omitted: the next occurrence of that time is used (today if still ahead, else tomorrow). A date can always be given explicitly, including today. A date + time in the past is rejected. (was A2) | Tim |
| D19 | 2026-11-10 | Personal to-dos have no assignees. (was A3) | Tim |
| D20 | 2026-11-10 | Server to-dos can be edited/deleted/reassigned by the creator, any assignee, or anyone with Manage Server. (was A4) | Tim |
| D21 | 2026-11-10 | Monthly rules come in two forms: n-th weekday (1st–4th or last) **and** day of month (1–31 or last day). A day that doesn't exist in a month falls back to that month's last day (31st → 30 Apr, 28/29 Feb). (was A5) | Tim |
| D22 | 2026-11-10 | Weekly rules may have multiple times per day. (was A6) | Tim |
| D23 | 2026-11-10 | A to-do can be completed while subtasks are unticked. (was A7) | Tim |
| D24 | 2026-11-10 | Server to-dos use the creator's timezone unless overridden. (was A8) | Tim |
| D25 | 2026-11-10 | Users who never set a timezone get `DEFAULT_TIMEZONE`, default **UTC**; the bot mentions this once. (was A10) | Tim |
| D26 | 2026-11-10 | A failed DM reminder is marked failed and the user is warned on their next command. (was A11) | Tim |
| D27 | 2026-11-10 | Command replies are ephemeral (only the invoker sees them); `/todo list post:true` shares a server list with the channel. (was A12) | Tim |
| D28 | 2026-11-10 | English only, for output **and** input (no Dutch keywords). (was A13) | Tim |
| D29 | 2026-11-10 | Up to **50 subtasks** per to-do. Discord select menus hold 25 options, so subtask pickers use two selects; message text is trimmed to Discord's embed limits (see §4.11). (was A14) | Tim |
| D30 | 2026-11-10 | The Pi runs 64-bit Raspberry Pi OS (`uname -m` = `aarch64`, `dpkg` = `arm64`); use standard `linux/arm64` images and wheels. (was A9) | Tim |
| D31 | 2026-11-10 | Python **3.12** (`requires-python = ">=3.12,<3.13"`, `python:3.12-slim` base image), replacing D16. Tim's dev machine has 3.12, so checks run locally in a `.venv`. | Tim |
| D32 | 2026-11-10 | `DEV_GUILD_ID` is replaced by `SYNC_GLOBAL` (bool, default true) + `SYNC_GUILD_IDS` (comma-separated). Never register a command both globally and in a guild (Discord then shows it twice). **`SYNC_GLOBAL=true`** (production) → global sync; every guild in `SYNC_GUILD_IDS` gets its guild commands deleted (cleanup after server-only mode). **`SYNC_GLOBAL=false`** (dev bot) → server-only mode: commands synced to the listed guilds (instant), global commands cleared, so DMs/user installs have none; config rejects it with an empty list. | Tim |
| D33 | 2026-11-10 | The env file lives at `configs/.env` (git-ignored with the rest of `configs/`), not the repo root. Both compose services load it via `env_file`; `config.py` reads it for local runs. `configs/.env.example` is the tracked template (`.gitignore` uses `configs/*` + `!configs/.env.example`). | Tim |
| D34 | 2026-11-11 | Internal data models use **pydantic** with `strict=True` + `frozen=True` (no type coercion; a wrong type is a bug and fails loudly). Applies to the service DTOs and inputs (`TodoView`, `SubtaskView`, `OccurrenceView`, `UpcomingItem`, `Page`, `DueReminder`, `GuildSettingsView`, `DueInput`, `TodoPatch`) and to `Actor`, `Outcome` and the effects (`DeleteMessage`). Test fakes may stay plain dataclasses. `TodoPatch` uses `model_fields_set` instead of an `UNSET` sentinel. | Tim |
| D35 | 2026-11-11 | `/todo upcoming` without `scope` in a server where the bot is installed replies with buttons **Server list / Personal list / Both** and shows the chosen view. Elsewhere (DMs, user-install only) it shows the personal list directly. An explicit `scope` skips the buttons. | Tim |
| D36 | 2026-11-11 | An admin can unset the reminder channel with `/sidequest channel clear:True` (Manage Server, same runtime check as setting it). `channel` and `clear:True` together is an error; clearing when none is set says so. Before clearing, the reply warns how many open timed server to-dos will stop reminding and offers **Confirm / Cancel** buttons. After confirming, reminders that come due without a channel are marked failed (`no_channel`), as today; existing reminder messages stay and keep working. New timed server to-dos are refused until a channel is set again. | Tim |

---

## 4. Functional spec

### 4.1 Lists and scope
- A to-do belongs to exactly one list: `server` (with a `guild_id`) or `personal` (owned by a user, no guild).
- Server to-dos are visible to every member of that server who uses the bot there.
- Personal to-dos are visible only to their owner, from anywhere (any server, DMs).
- Server-list commands only work in a server where the bot is installed. Personal-list commands work everywhere (the app is both guild- and user-installable).

### 4.2 To-do kinds
| Kind | When | Reminder |
|---|---|---|
| One-time, untimed | no date, no time | none; only visible via commands |
| One-time, timed | date + time (date may be omitted on input → next occurrence of that time, D18) | one reminder at that moment |
| Repeating | always has a rule + time(s) | one reminder per occurrence |

A date without a time is rejected (D17).

### 4.3 Repeating rules
All times are wall-clock times in the to-do's timezone; they stay at the same local time across DST.
- **Daily** at one or more times — "every day at 08:00 and 20:00".
- **Weekly** on one or more weekdays at one or more times — "every Monday and Thursday at 12:00".
- **Monthly (weekday)** on the n-th weekday of the month (1st–4th or last) at one or more times — "every first Sunday of the month at 12:00".
- **Monthly (day)** on a day of the month (1–31 or last day) at one or more times — "on the 15th of every month at 09:00". A day a month doesn't have falls back to its last day (D21).

DST: a nonexistent local time (spring-forward gap) shifts forward by the gap; an ambiguous time (fall-back) fires once, at the first instance.

### 4.4 Subtasks (D4)
- Ordered checklist items with a title; anyone who may see the to-do may tick them.
- On repeating to-dos all subtasks reset whenever an occurrence is closed (done or missed).
- Completing a to-do with unticked subtasks is allowed (D23).

### 4.5 Details (D9)
- Optional multi-line text, ≤ 4000 chars, set via a modal (on create, or later via `/todo details`).
- Shown in the reminder and in `/todo show`.

### 4.6 Assignees
- Server to-dos: one or more assignees; defaults to the creator. Reminders ping all assignees.
- Personal to-dos: no assignees; the owner is implicit (D19).

### 4.7 Timezones and time I/O
- Each user can set a default timezone (IANA name, autocomplete). Fallback when unset: `DEFAULT_TIMEZONE` env (default `UTC`) (D25).
- Every create command takes an optional `timezone` override. The to-do stores the timezone it was created in.
- Input (English only, D28): times `HH:MM` 24h only; dates `YYYY-MM-DD` or `DD-MM-YYYY` (separators `-`, `/`, `.`), plus `today`/`tomorrow`.
- Output: points in time → Discord timestamps via one helper module. Never `strftime` a point in time into user-facing text.

### 4.8 Reminders
- **Server:** posted in the server's reminder channel; content pings the assignees (users only — never roles/everyone); an embed shows title, details, due time, rule description, subtasks; components: **Done** button and (if subtasks exist) a subtask multi-select.
- **Personal:** same message, sent as a DM to the owner.
- **Done:** completes the occurrence (and a one-time to-do), then deletes the reminder message. Anyone who can see it may press it (D3).
- Repeating: a new occurrence replaces an unchecked previous reminder (D7).
- Bot was down: overdue reminders are posted on startup, marked late. A repeating to-do never floods — at most one catch-up reminder.
- A to-do checked off before it is due (via `/todo upcoming` or `/todo done`) never sends that reminder. For repeating to-dos this skips only that occurrence.

### 4.9 Where to-dos are shown
- Timed: reminder message at due time, and `/todo upcoming` (check off early from there).
- Untimed: only via `/todo list` and `/todo show`.
- Command responses are ephemeral by default; `/todo list post:true` shares a server list publicly (D27).

### 4.10 Permissions
| Action | Server to-do | Personal to-do |
|---|---|---|
| View, tick subtasks, complete | any member in that server (D3) | owner |
| Create | any member | owner |
| Edit, details, assign, subtask add/remove, delete | creator, any assignee, or Manage Server (D20) | owner |
| Set reminder channel | Manage Server | — |

### 4.11 Limits (D29)
Title ≤ 200 chars · details ≤ 4000 · subtask title ≤ 100 · subtasks ≤ 50 per to-do · assignees ≤ 10 · times per rule ≤ 12.

Discord limits the code must respect when rendering:
- A select menu holds at most 25 options → subtask pickers use up to two selects (1–25, 26–50). Option labels are cut to 100 chars.
- All embeds in one message share a 6000-char budget (description ≤ 4096). Render details first, then as many subtasks as fit, then "… and N more" — the selects always contain every subtask.

---

## 5. Architecture

### 5.1 Stack
| Concern | Choice |
|---|---|
| Language | Python 3.12 (D31) |
| Discord | discord.py 2.7.x, `Intents.none()` |
| DB | PostgreSQL 17 (Docker), SQLAlchemy 2 async + asyncpg, Alembic |
| Config | pydantic-settings (env vars / `configs/.env`, D33) |
| Timezones | `zoneinfo` + `tzdata` pip package (slim images lack system tzdata) |
| Packaging | `pyproject.toml` (hatchling, src layout), pip-tools → `requirements.txt`, `requirements-dev.txt` |
| Quality | ruff (lint + format), pytest + pytest-asyncio |
| Deploy | Docker Compose on Raspberry Pi (aarch64), `update.sh` |

### 5.2 Layers
```
            ┌──────────────┐   ┌──────────────┐   ┌───────────────────────┐
 Discord ──▶│  bot/        │   │  scheduler/  │   │  web/  (future, FastAPI)│
            │  adapter     │   │  loop        │   │                       │
            └──────┬───────┘   └──────┬───────┘   └──────────┬────────────┘
                   ▼                  ▼                      ▼
            ┌──────────────────────────────────────────────────────────┐
            │ services/   domain operations + permissions (no discord) │
            └──────────────────────────┬───────────────────────────────┘
                   ┌───────────────────┴──────────────┐
                   ▼                                  ▼
            ┌──────────────┐                  ┌──────────────────────┐
            │ db/  ORM,    │                  │ core/  pure: time     │
            │ sessions     │                  │ parsing, recurrence,  │
            └──────────────┘                  │ discord_time, errors  │
                                              └──────────────────────┘
```
Import rules (enforced by a test): `core` imports neither `discord` nor `sqlalchemy`; `services` and `db` never import `discord`; only `bot/` imports `discord`.

### 5.3 Package layout
```
pyproject.toml  requirements.txt  requirements-dev.txt
Dockerfile  compose.yaml  compose.test.yaml  update.sh
configs/.env.example        # template; real configs/.env + configs/git.env are git-ignored (D33)
.gitattributes  .gitignore  .dockerignore
scripts/compile-requirements.sh
migrations/                 # alembic (env.py, versions/)
src/sidequest/
  __init__.py  __main__.py  cli.py  config.py  logging.py
  core/       errors.py  clock.py  timeparse.py  tz.py  recurrence.py  discord_time.py  limits.py
  db/         base.py  models.py  session.py
  services/   actor.py  settings.py  todos.py  subtasks.py  occurrences.py  permissions.py  effects.py
  scheduler/  loop.py  signal.py  notifier.py      # notifier = Protocol; bot implements it
  bot/        client.py  errors.py  autocomplete.py  render.py
              commands/ todo.py  repeat.py  subtask.py  settings.py  admin.py
              views/    reminder.py  listing.py  upcoming.py  modals.py  assign.py
tests/  unit/  integration/
```

### 5.4 Gateway & intents (answer to Tim's open question)
Fully possible. With `Intents.none()` the bot still receives every slash command, button, select, modal submit and autocomplete event. Consequences the code must respect:
- No guild/channel/member cache. Work with IDs: `interaction.guild_id`, `interaction.channel_id`, `interaction.permissions` (the invoker's resolved permissions come with the interaction).
- Post to channels via `client.get_partial_messageable(channel_id)`; delete via partial messages. DMs via `client.create_dm(discord.Object(user_id))`.
- When an admin sets the reminder channel, validate it by posting a short confirmation message there (proves the bot can send).
- **DM limitation:** Discord only lets a bot DM a user it shares a server with (and who allows DMs). Users with only a personal list must share at least one server with the bot. A failed DM is recorded and the user is warned on their next command (S6). Verify whether a user-install alone suffices during S6.
  - *S6 (2026-11-11):* not verified yet: Claude can't use Discord, so it's on Tim's manual checklist (a test account that has the app user-installed and shares no server with the bot). Until then, assume a shared server is required. The code doesn't depend on the answer: a refused DM is recorded as `dm_closed` and the user is warned on their next command (D26).

### 5.5 Scheduling model
- `occurrences` table holds concrete reminder instances. A timed one-time to-do has one; a repeating to-do always has exactly one **pending** future occurrence (materialized one at a time).
- Scheduler loop: claim due pending occurrences (`FOR UPDATE SKIP LOCKED`) → mark sent + materialize next + close previous (missed) in one transaction → post the message → store message IDs. A startup sweep re-posts occurrences marked sent but without a message ID (crash recovery).
- Sleeps until the next due time, capped at 60 s, or until woken by an in-process signal after any change.

### 5.6 Room for the web frontend (not built now)
- All business rules live in `services/`, which take an `Actor` (user id, guild id or none, Manage Server flag, origin) — the web app constructs the same `Actor` after Discord OAuth2 login (user IDs are Discord snowflakes, so no user mapping is needed).
- Services never call Discord. They return **effects** (e.g. "delete message X in channel Y") that the bot adapter executes. A future web process can write those effects to an `outbox` table the bot drains.
- The scheduler picks up changes made by another process within 60 s (poll cap); Postgres `LISTEN/NOTIFY` can be added behind the `scheduler/signal.py` interface later.
- The CLI reserves `sidequest web`; compose will gain a `web` service.
- DB stores UTC instants + the to-do's timezone, so any client can render correctly.

---

## 6. Segments

| Seg | Title | Depends on | Notes |
|---|---|---|---|
| S1 | Foundation | — | Deployable "hello" bot; deploy to the Pi early to catch arm64 issues |
| S2 | Data model | S1 | Can run in parallel with S3 |
| S3 | Time & recurrence | S1 | Pure code, no DB/Discord |
| S4 | Services | S2, S3 | Discord-free domain layer |
| S5 | Commands | S4 | Slash commands + views (not reminders) |
| S6 | Reminders | S4 (S5 for shared render helpers) | Scheduler, reminder messages, DMs |
| S7 | Ops & hardening | S1–S6 | Health, backups, retention, runbook, final review |

---

## 7. Open assumptions

None. A1–A14 were reviewed by Tim on 2026-11-10 and are now decisions D17–D30.

---

## 8. Out of scope (for now)
Web frontend · snooze buttons · role assignees · "every N days/weeks" intervals · date-only to-dos · per-server default timezone · localisation · notification digests.
