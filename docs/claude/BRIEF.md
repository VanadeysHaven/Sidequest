# Sidequest — Project brief

> Owner: Tim. Written by Claude (Opus 5.5), 2026-11-10.
> This is the source of truth for *what* we build. `WORKFLOW.md` covers *how* Claude works.
> Change rules: new decisions are appended to §3 with a date. Existing decisions change only with Tim's approval.

---

## 1. What Sidequest is

A Discord bot for to-dos, written in Python, running in Docker on a Raspberry Pi.
It only works in servers where it is installed (no DMs, D40).

- A server has **named lists** (D41). Every server has a **Default List** that is open to every member (D42, D51); anyone can create more lists, which they own and share with **collaborators** (D46, D50).
- Each user picks their own **default list** per server with `/settings default-list` (D45).
- To-dos can have assignees; reminders are posted in the server's reminder channel, pinging the assignees.

*(Until S8 there was one server list plus a personal list per user with DM reminders; see D2/D5, superseded by D40.)*

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
| D2 | 2026-11-10 | ~~One shared list per server **plus** one personal list per user.~~ Superseded by D40/D41. | Tim |
| D3 | 2026-11-10 | ~~Anyone who can see a server reminder can check it off.~~ Superseded by D50/D51. Checking off still completes it for everyone. | Tim |
| D4 | 2026-11-10 | Subtasks are simple checklist items (no own time/assignee). On repeating to-dos they reset for each new occurrence. | Tim |
| D5 | 2026-11-10 | ~~The personal list is global (all servers + DMs with the bot). Personal reminders are sent as DMs.~~ Superseded by D40. | Tim |
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
| D19 | 2026-11-10 | ~~Personal to-dos have no assignees. (was A3)~~ Superseded by D40. | Tim |
| D20 | 2026-11-10 | ~~Server to-dos can be edited/deleted/reassigned by the creator, any assignee, or anyone with Manage Server. (was A4)~~ Superseded by D50/D51. | Tim |
| D21 | 2026-11-10 | Monthly rules come in two forms: n-th weekday (1st–4th or last) **and** day of month (1–31 or last day). A day that doesn't exist in a month falls back to that month's last day (31st → 30 Apr, 28/29 Feb). (was A5) | Tim |
| D22 | 2026-11-10 | Weekly rules may have multiple times per day. (was A6) | Tim |
| D23 | 2026-11-10 | A to-do can be completed while subtasks are unticked. (was A7) | Tim |
| D24 | 2026-11-10 | Server to-dos use the creator's timezone unless overridden. (was A8) | Tim |
| D25 | 2026-11-10 | Users who never set a timezone get `DEFAULT_TIMEZONE`, default **UTC**; the bot mentions this once. (was A10) | Tim |
| D26 | 2026-11-10 | ~~A failed DM reminder is marked failed and the user is warned on their next command. (was A11)~~ Superseded by D40. | Tim |
| D27 | 2026-11-10 | Command replies are ephemeral (only the invoker sees them); `/todo list post:true` shares a server list with the channel. (was A12) | Tim |
| D28 | 2026-11-10 | English only, for output **and** input (no Dutch keywords). (was A13) | Tim |
| D29 | 2026-11-10 | Up to **50 subtasks** per to-do. Discord select menus hold 25 options, so subtask pickers use two selects; message text is trimmed to Discord's embed limits (see §4.11). (was A14) | Tim |
| D30 | 2026-11-10 | The Pi runs 64-bit Raspberry Pi OS (`uname -m` = `aarch64`, `dpkg` = `arm64`); use standard `linux/arm64` images and wheels. (was A9) | Tim |
| D31 | 2026-11-10 | Python **3.12** (`requires-python = ">=3.12,<3.13"`, `python:3.12-slim` base image), replacing D16. Tim's dev machine has 3.12, so checks run locally in a `.venv`. | Tim |
| D32 | 2026-11-10 | `DEV_GUILD_ID` is replaced by `SYNC_GLOBAL` (bool, default true) + `SYNC_GUILD_IDS` (comma-separated). Never register a command both globally and in a guild (Discord then shows it twice). **`SYNC_GLOBAL=true`** (production) → global sync; every guild in `SYNC_GUILD_IDS` gets its guild commands deleted (cleanup after server-only mode). **`SYNC_GLOBAL=false`** (dev bot) → server-only mode: commands synced to the listed guilds (instant), global commands cleared, so DMs/user installs have none; config rejects it with an empty list. | Tim |
| D33 | 2026-11-10 | The env file lives at `configs/.env` (git-ignored with the rest of `configs/`), not the repo root. Both compose services load it via `env_file`; `config.py` reads it for local runs. `configs/.env.example` is the tracked template (`.gitignore` uses `configs/*` + `!configs/.env.example`). | Tim |
| D34 | 2026-11-11 | Internal data models use **pydantic** with `strict=True` + `frozen=True` (no type coercion; a wrong type is a bug and fails loudly). Applies to the service DTOs and inputs (`TodoView`, `SubtaskView`, `OccurrenceView`, `UpcomingItem`, `Page`, `DueReminder`, `GuildSettingsView`, `DueInput`, `TodoPatch`) and to `Actor`, `Outcome` and the effects (`DeleteMessage`). Test fakes may stay plain dataclasses. `TodoPatch` uses `model_fields_set` instead of an `UNSET` sentinel. | Tim |
| D35 | 2026-11-11 | ~~`/todo upcoming` without `scope` in a server where the bot is installed replies with buttons **Server list / Personal list / Both** and shows the chosen view. Elsewhere (DMs, user-install only) it shows the personal list directly. An explicit `scope` skips the buttons.~~ Superseded by D49. | Tim |
| D36 | 2026-11-11 | An admin can unset the reminder channel with `/sidequest channel clear:True` (Manage Server, same runtime check as setting it). `channel` and `clear:True` together is an error; clearing when none is set says so. Before clearing, the reply warns how many open timed server to-dos will stop reminding and offers **Confirm / Cancel** buttons. After confirming, reminders that come due without a channel are marked failed (`no_channel`), as today; existing reminder messages stay and keep working. New timed server to-dos are refused until a channel is set again. | Tim |
| D37 | 2026-11-11 | `/todo show` → **Done**: the embed and components disappear; the message becomes only "✅ Checked off **title**.", plus "Next: <timestamp>" (Discord timestamp) for a repeating to-do with a next occurrence. The same wording is used everywhere something is checked off: `/todo done`, `/todo upcoming`, a reminder's Done button. `/todo upcoming` keeps showing its refreshed list below. | Tim |
| D38 | 2026-11-12 | A stuck bot restarts by itself. Docker only *marks* a container unhealthy, so a watchdog thread in the bot (`health.Watchdog`) exits the process when the scheduler heartbeat hasn't changed for 3 minutes (or is missing 5 minutes after start), and `restart: unless-stopped` restarts it. A thread still fires when the event loop is blocked. Time is measured on a monotonic clock, because the Pi's wall clock jumps forward when NTP syncs after boot. Chosen over an autoheal container, which needs the Docker socket (root-equivalent access to the Pi). The Docker `HEALTHCHECK` stays for visibility in `docker compose ps`. Side effect: while the database is down the bot restarts every few minutes. | Tim (requirement), Claude (mechanism) |
| D39 | 2026-11-12 | To-do **details** render Discord markdown (bold, lists, links) in reminders and `/todo show`; only mentions are escaped. Titles and subtask titles stay fully escaped (mentions + markdown). The restart loop on a persistent scheduler error (D38) is accepted. | Tim |
| D40 | 2026-11-12 | **No personal lists, no DMs.** Sidequest only works in servers where the bot is installed. Commands are guild-install + guild-context only (no user install, no DMs, no group DMs). Reminders are only posted in the server's reminder channel. Supersedes D2, D5, D19, D26 and D35. The DM verification and the "commands don't work in DMs" future-work item are closed. | Tim |
| D41 | 2026-11-12 | A server has **any number of named lists** (max 25). Each to-do belongs to exactly one list. One reminder channel per server for all lists (D6 unchanged). | Tim |
| D42 | 2026-11-12 | Every server has a **"Default List"**, its *fallback list*: users who never picked a default get it. It can be renamed but **not deleted**. Migration `0003` creates it for existing servers; for new servers it is created the first time anyone uses Sidequest there (the bot has no `guilds` intent, D11, so it never hears about joining). | Tim (list), Claude (mechanism) |
| D43 | 2026-11-12 | **List names** are unique per server, **case-insensitive**, trimmed, 1–50 characters. | Tim |
| D44 | 2026-11-12 | **To-do titles** are unique among the **open** to-dos of one list, **case-insensitive**. Done and deleted to-dos don't count. Checked on create, title edit and move. | Tim |
| D45 | 2026-11-12 | Each user can choose a **default list per server** with `/settings default-list`. Commands without a `list` option use it. If it is unset, or that list was deleted, the server's fallback list is used. | Tim |
| D46 | 2026-11-12 | **Managing lists:** anyone in the server can create a list and becomes its **owner**. Renaming, deleting, managing collaborators and transferring ownership need the owner or Manage Server. The fallback list has **no owner** (D51). | Tim |
| D47 | 2026-11-12 | **Deleting a list** with open to-dos asks: **Delete them** (cancelled, reminder messages deleted), **Move them** to another list (select), or **Cancel**. A move is refused if any title would clash on the target list; the reply names the clashing titles. An empty list gets Delete/Cancel. Finished history on a deleted list is deleted with it. | Tim |
| D48 | 2026-11-12 | **`/todo move`** moves one to-do to another list in the same server (edit rights on its list, add rights on the target, title must not clash). Reminders, subtasks and assignees stay. | Tim |
| D49 | 2026-11-12 | Commands that show to-dos take an optional `list` option and show **one** list. `/todo list` without `list` shows your default list (D45). `/todo upcoming` without `list` uses **your own default-list setting only**; if you haven't set one, `list` is required and the reply says so. The Server/Personal/Both buttons (D35) are gone. Places that mix lists (autocomplete) show the list name next to the title. | Tim |
| D50 | 2026-11-12 | **Collaborators.** Every list except the fallback list has an **owner** and up to 25 **collaborators**. Everyone in the server can **see** every list. Only the owner, collaborators and Manage Server can **add, edit, set details, assign, add/remove subtasks, delete, move, check off** to-dos and **tick subtasks** on it, also via a reminder's Done button and subtask select. Replaces D3 and D20 for these lists. Collaborators can't rename/delete the list or manage collaborators. Assignees don't have to be collaborators: they still get pinged. | Tim |
| D51 | 2026-11-12 | **The fallback list is open to everyone.** Every member can add, edit, delete, assign, move and check off its to-dos and tick subtasks. Only **Manage Server** can **rename** it. It never has an owner or collaborators, can't be transferred, and **can't be deleted by anyone**, not even Manage Server. | Tim |
| D52 | 2026-11-12 | **Transferring ownership:** `/lists transfer` by the owner or Manage Server; not for the fallback list. The new owner must be a server member and not a bot; if they were a collaborator they stop being one. The **old owner becomes a collaborator**; if that would exceed 25 collaborators, the transfer is refused ("remove a collaborator first"). | Tim |
| D53 | 2026-11-12 | `/settings default-list` only accepts a list you can add to-dos to. If you later lose that right, `/todo add` without `list` says so and names the list, rather than silently picking another. | Tim |

---

## 4. Functional spec

### 4.1 Lists
- Sidequest only works in servers where the bot is installed (D40). Every command is guild-install, server-only.
- A server has up to 25 named lists (D41). Names are unique per server, case-insensitive, 1–50 characters (D43).
- Every server has an ownerless fallback list, "Default List" (D42): open to every member (D51), renamable only with Manage Server, never deletable. It is created on first use.
- Other lists have an owner (the creator, D46) and up to 25 collaborators (D50). Ownership can be transferred (D52).
- A to-do belongs to exactly one list; open titles are unique per list, case-insensitive (D44). `/todo move` moves it (D48).
- Every member sees every list and its to-dos. Who may change them: §4.10.
- Each user may pick a default list per server (D45, D53); commands without `list` use it, else the fallback list. `/todo upcoming` needs the user's own setting or an explicit `list` (D49).

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
- One or more assignees; defaults to the creator. Reminders ping all assignees. Assignees don't have to be collaborators of the list (D50).

### 4.7 Timezones and time I/O
- Each user can set a default timezone (IANA name, autocomplete). Fallback when unset: `DEFAULT_TIMEZONE` env (default `UTC`) (D25).
- Every create command takes an optional `timezone` override. The to-do stores the timezone it was created in.
- Input (English only, D28): times `HH:MM` 24h only; dates `YYYY-MM-DD` or `DD-MM-YYYY` (separators `-`, `/`, `.`), plus `today`/`tomorrow`.
- Output: points in time → Discord timestamps via one helper module. Never `strftime` a point in time into user-facing text.

### 4.8 Reminders
- Posted in the server's reminder channel; content pings the assignees (users only — never roles/everyone); an embed shows title, details, due time, rule description, subtasks, and the list name in the footer; components: **Done** button and (if subtasks exist) a subtask multi-select.
- **Done:** completes the occurrence (and a one-time to-do), then deletes the reminder message. Allowed for whoever may check off on that list (D50/D51); anyone else gets an ephemeral refusal and the reminder stays.
- Repeating: a new occurrence replaces an unchecked previous reminder (D7).
- Bot was down: overdue reminders are posted on startup, marked late. A repeating to-do never floods — at most one catch-up reminder.
- A to-do checked off before it is due (via `/todo upcoming` or `/todo done`) never sends that reminder. For repeating to-dos this skips only that occurrence.

### 4.9 Where to-dos are shown
- Timed: reminder message at due time, and `/todo upcoming` (check off early from there).
- Untimed: only via `/todo list` and `/todo show`.
- Command responses are ephemeral by default; `/todo list post:true` shares a list publicly (D27).

### 4.10 Permissions
"Member" = anyone in that server. Manage Server may do everything on owned lists; the scheduler (system actor) passes every check.

| Action | Owned list (D50) | Fallback list "Default List" (D51) |
|---|---|---|
| See the list and its to-dos | any member | any member |
| Check off (command, upcoming, reminder Done), tick subtasks | owner, collaborators, Manage Server | any member |
| Add a to-do (incl. moving one *onto* the list) | owner, collaborators, Manage Server | any member |
| Edit, details, assign, subtask add/remove, delete, move *off* the list | owner, collaborators, Manage Server | any member |
| Rename the list | owner, Manage Server | Manage Server only |
| Delete the list, set collaborators, transfer | owner, Manage Server | nobody (Manage Server neither) |
| Create a list | any member | — |
| Set reminder channel | Manage Server | — |

### 4.11 Limits (D29)
Title ≤ 200 chars · details ≤ 4000 · subtask title ≤ 100 · subtasks ≤ 50 per to-do · assignees ≤ 10 · times per rule ≤ 12 · list name ≤ 50 · lists ≤ 25 per server · collaborators ≤ 25 per list.

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
  services/   actor.py  settings.py  lists.py  todos.py  subtasks.py  occurrences.py  permissions.py  effects.py
  scheduler/  loop.py  signal.py  notifier.py      # notifier = Protocol; bot implements it
  bot/        client.py  errors.py  autocomplete.py  render.py
              commands/ todo.py  repeat.py  subtask.py  settings.py  admin.py  lists.py
              views/    reminder.py  listing.py  upcoming.py  modals.py  assign.py  list_delete.py  collaborators.py
tests/  unit/  integration/
```

### 5.4 Gateway & intents (answer to Tim's open question)
Fully possible. With `Intents.none()` the bot still receives every slash command, button, select, modal submit and autocomplete event. Consequences the code must respect:
- No guild/channel/member cache. Work with IDs: `interaction.guild_id`, `interaction.channel_id`, `interaction.permissions` (the invoker's resolved permissions come with the interaction).
- Post to channels via `client.get_partial_messageable(channel_id)`; delete via partial messages. DMs via `client.create_dm(discord.Object(user_id))`.
- When an admin sets the reminder channel, validate it by posting a short confirmation message there (proves the bot can send).
- No DMs (D40).

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
| S8 | Server lists | S1–S7 | Drop personal lists/DMs; named lists, collaborators, default list per user, migration `0003` |

---

## 7. Open assumptions

None. A1–A14 were reviewed by Tim on 2026-11-10 and are now decisions D17–D30.

---

## 8. Out of scope (for now)
Web frontend · snooze buttons · role assignees · "every N days/weeks" intervals · date-only to-dos · per-server default timezone · localisation · notification digests.
