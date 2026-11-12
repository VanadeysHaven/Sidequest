# Sidequest — what Claude Code needs to know

> Written by Claude (Opus 5.5), 2026-11-12. Replaces the segment setup (S1–S9), which is archived in
> `docs/claude/archive/initial-release/`. Read this file, then only the brief for the feature you're working on.

Sidequest is a Discord to-do bot for servers: Python 3.12, discord.py, PostgreSQL 17, Docker Compose on
Tim's Raspberry Pi (64-bit, arm64). Tim develops on Windows and deploys on the Pi with `update.sh`.
A web frontend may come later; it is out of scope, but the layering leaves room for it.

---

## 1. How to work

### Feature workflow
1. Every feature has a brief: `docs/claude/briefs/<slug>.md`. Its **Status** line (top of the file)
   says where it stands: `drafting` → `ready` → `in progress` → `waiting for review` → `done`.
2. A session reads this file and **only** the brief it's working on. Don't read the archive unless the
   brief points there.
3. Check git with read-only commands (`git status`, `git branch --show-current`, `git diff --stat`). If
   another feature's changes are still uncommitted, stop and ask Tim to commit first. Otherwise create
   `claude/<slug>`.
4. Turn the brief's checklist into a task list and work through it.
5. Run the checks (§7). Never call a feature done with failing checks.
6. At the end: tick the checklist, set the Status, and add a short **Handoff** section to the brief
   (what was built, deviations and why, open questions). If a decision changed something this file
   describes, update this file too (the decision log in §6 and the affected section).
7. Stop and report to Tim: what was built, files changed, deviations, open questions, the manual test
   checklist and a suggested commit message. Don't start the next feature.

A new feature request from Tim starts with a brief, not code: ask the design questions that matter,
write the brief with his answers, set it to `ready`, and stop.

If the spec is unclear, **ask Tim rather than guessing.** Subagents stop and report instead of deciding.

### Git (hard rules)
- Allowed: `status`, `diff`, `log`, `show`, `branch`, and creating a branch (`git switch -c`).
- **Never**: `commit`, `push`, `merge`, `rebase`, `reset`, `stash`, `clean`, `checkout -- <file>`,
  `restore`, `cherry-pick`, `tag`, `git mv`/`git rm`/`git add`, or anything touching remotes. **No worktrees.**
- Never switch branches with uncommitted changes.
- New executable files: tell Tim to run `git add --chmod=+x <file>` (Windows loses the bit).

### Models and context
| Work | Who |
|---|---|
| Documentation (this file, briefs, `RUNBOOK.md`, root `README.md`) | **Opus 5.5** only |
| Design, schema, recurrence, scheduler, services & permissions, reviews | Main session |
| Boilerplate from an exact spec; repeating an established pattern | Haiku subagent, reviewed |
| Table-driven tests from a case list in the brief | Haiku subagent, reviewed |
| Running checks and summarising failures; mechanical lint fixes | Haiku subagent |
| Broad codebase searches | Explore agent |

Subagent prompts are self-contained (exact spec excerpt, paths, conventions, acceptance check), ask
for a short report (files, commands, results), and spawn Haiku with `model: "haiku"`.
Keep context small: targeted `grep`/reads, source files under ~400 lines, bulky runs in subagents.

---

## 2. Hard constraints (Tim)

- Python backend; Discord slash commands; **no gateway intents** (`Intents.none()`).
- Runs on the Pi in Docker Compose. The `sidequest` CLI starts the bot.
- Database is relational and **not SQLite** (PostgreSQL 17).
- Times are **entered** as 24h `HH:MM` only. Every **point in time** shown to users is a Discord
  timestamp (`<t:unix:style>`), via `core.discord_time`. Wall-clock text ("every Monday at 12:00")
  is 24h.
- Requirements are compiled from `pyproject.toml` with pip-tools: edit `pyproject.toml`, run
  `scripts/compile-requirements.sh`. Never hand-edit `requirements*.txt`.
- English only, for input and output.

---

## 3. Architecture

### Stack
discord.py 2.7 (`app_commands`, `ui.DynamicItem` for restart-proof components) · SQLAlchemy 2 async +
asyncpg + Alembic · pydantic + pydantic-settings · `zoneinfo` + `tzdata` · ruff · pytest + pytest-asyncio
· hatchling, src layout.

### Layers (enforced by `tests/unit/test_layering.py`)
```
bot/ (discord)   scheduler/ (no discord)   [web/ later]
        \              |                    /
         services/  — every business rule + permissions, no discord
        /                        \
   db/ (ORM, sessions)        core/ (pure: time, recurrence, errors, limits)
```
- `core` imports neither `discord` nor `sqlalchemy` nor `sidequest.db`.
- `services`, `db` and `scheduler` never import `discord`. Only `bot/` does.

### Package map (`src/sidequest/`)
| Path | What's there |
|---|---|
| `cli.py`, `config.py`, `logging.py`, `health.py` | CLI (`sidequest`, `migrate`, `healthcheck`), settings, logging, heartbeat watchdog |
| `core/` | `clock` (`Clock` protocol, `SystemClock`), `timeparse`, `tz`, `recurrence` (rules, `next_occurrence`, `describe`, `anchored`), `discord_time`, `enums`, `errors`, `limits`, `text` (`bold()` for service messages) |
| `db/` | `base`, `models` (full schema), `session`, `migrate` |
| `services/` | `todos`, `occurrences` (check-off, upcoming, scheduler API), `undo`, `subtasks`, `lists`, `settings`, `permissions`, `retention`, `meta`; plumbing: `uow`, `actor`, `dto`, `effects`, `model` (`StrictModel`), `_common` (shared helpers) |
| `scheduler/` | `loop` (`Scheduler`), `notifier` (Protocol), `signal` (`ScheduleSignal`), `retention` |
| `bot/` | `client`, `adapter` (glue: `actor_from`, `uows`, `apply`, `reply`, `defer`, …), `render` (all embeds/text, no I/O), `options` (option → rule/patch parsing), `autocomplete`, `errors`, `notifier` (`DiscordNotifier`) |
| `bot/commands/` | `todo` (+ `todo_edit`, `todo_list`, `todo_manage`, `todo_view`), `repeat`, `subtask`, `lists`, `settings`, `admin`, `about`, `common` |
| `bot/views/` | `base` (`BaseView`/`BaseModal`, 5-min, owner-only), `reminder` (persistent Done + subtask selects), `show`, `upcoming`, `listing`, `assign`, `confirm` (+ check-off confirm), `undo`, `list_delete`, `collaborators`, `modals` |
| `migrations/versions/` | `0001`–`0003`. New: `alembic revision --rev-id 0004 -m "..."` |
| `tests/` | `unit/`, `integration/` (real Postgres), `support/` (`FixedClock`, `FakeNotifier`) |

### How the pieces talk
- **Services** take a `Uow` (session + clock + default timezone) and an `Actor` (user id, guild id,
  Manage Server flag, origin). Each mutating call locks the to-do row (`FOR UPDATE`) first, commits
  itself, and returns `Outcome(value, effects, changed_schedule)`.
- **Effects** (e.g. `DeleteMessage`) are what services want done in Discord; the bot runs them
  (`adapter.apply` also wakes the scheduler when `changed_schedule`). Services never call Discord.
- **Errors** are `SidequestError` subclasses with a user-safe `.message` (`NotFound`, `Forbidden`,
  `InvalidOperation`, `NameTaken`, `LimitExceeded`, `InvalidRule`, `InPast`, …). Commands raise; the tree
  error handler, `BaseView.on_error` and `BaseModal.on_error` show the message ephemerally and log the rest.
- **Command pattern:** `adapter.defer` → `actor_from` → service call(s) + `collect_notes` in one
  `async with adapter.uows(interaction)() as uow:` → `apply` → `reply`. Replies are ephemeral and use
  `AllowedMentions.none()`.
- **Persistent components** are `DynamicItem`s registered in `client.setup_hook`
  (`add_dynamic_items`). custom_id scheme: `sq:occ:done:<occurrence_id>`, `sq:occ:sub:<occurrence_id>:<page>`.
  Everything else uses `BaseView` (in memory, 5 minutes, gone after a restart).
- **Scheduler:** the DB is the schedule. The loop claims due pending occurrences
  (`FOR UPDATE SKIP LOCKED`), marks them sent, closes the previous unchecked one as missed, materializes
  the next one, then posts via the `Notifier` and stores the message id (`attach_message`). It sleeps
  until the next due time (1–60 s) or until `ScheduleSignal.wake()`. Every iteration it also re-posts
  occurrences that are `sent` without a message and were claimed > 60 s ago (crash recovery), then
  writes the heartbeat (`/tmp/sidequest-heartbeat`); the watchdog restarts the bot if it goes stale.

---

## 4. Domain rules

### Lists and permissions
- Server-only: no DMs, no user installs, no personal lists.
- A server has up to 25 named lists; names unique per server, case-insensitive, 1–50 chars.
- Every server has an ownerless fallback list, **"Default List"**, created on first use. Any member may
  work on it; only Manage Server may rename it; nobody may delete it.
- Other lists have an owner (the creator) and up to 25 collaborators; ownership can be transferred
  (the old owner becomes a collaborator).
- Each user may set a default list per server (`/settings default-list`); commands without `list` use it,
  else the fallback. `/todo upcoming` needs the user's own setting or an explicit `list`.
- Every member sees every list.

| Action | Owned list | Default List |
|---|---|---|
| Check off, tick subtasks (commands, upcoming, reminder) | owner, collaborators, Manage Server | any member |
| Add / edit / details / assign / subtasks / delete / move | owner, collaborators, Manage Server | any member |
| Rename list | owner, Manage Server | Manage Server |
| Delete list, collaborators, transfer | owner, Manage Server | nobody |
| Set reminder channel | Manage Server | — |

Assignees don't need to be collaborators; they're still pinged. The scheduler's system actor passes
every check.

### To-dos
- Kinds: **one-time untimed** (no reminder), **one-time timed** (date + time, one reminder), **repeating**
  (rule + times). A date without a time is rejected; a time without a date means the next time it comes
  round (today or tomorrow); a past date + time is rejected.
- Open titles are unique per list, case-insensitive (`uq_todos_list_id_open_title`).
- Statuses: to-do `open` / `done` / `cancelled` (deleted). Done and deleted to-dos stay as history;
  `HISTORY_RETENTION_DAYS` optionally purges old history.
- Details: optional, ≤ 4000 chars, via a modal, render Discord markdown (mentions escaped). Titles and
  subtask titles are fully escaped.
- Subtasks: ≤ 50, simple checklist items. On repeating to-dos they reset whenever an occurrence is closed
  (done or missed). A to-do can be completed with unticked subtasks.
- Assignees: ≤ 10, default the creator.
- Timezones: per user (`/settings timezone`), else `DEFAULT_TIMEZONE` (default UTC, mentioned once).
  Create commands take a `timezone` override; the to-do stores its zone. Dates: `YYYY-MM-DD`,
  `DD-MM-YYYY` (`-`, `/`, `.`), `today`, `tomorrow`.

### Repeating rules (`core/recurrence.py`, stored as JSONB)
Daily · weekly (weekdays, `every` 1–52 weeks, optional `start` date; weeks run Mon–Sun) · monthly by
n-th weekday (1st–4th, last) · monthly by day (1–31, last; missing days fall back to the month's last
day). Multiple times per day. Times are wall-clock in the to-do's zone; a DST gap shifts forward, an
ambiguous time fires once (first instance). Changing the rule *type* on edit is refused ("delete and add
again").

### Occurrences and reminders
- `occurrences` are concrete reminder instances. Status flow: `pending` → `sent` → `done` / `missed`;
  `pending` → `done` (checked off early) or `cancelled` (edited/deleted); `sent` → `failed`.
- At most one `pending` and one `sent` per to-do (partial unique indexes). A repeating to-do always
  has exactly one pending future occurrence.
- Reminders go to the server's one reminder channel (Manage Server sets/clears it), ping the assignees
  (users only), show an embed (title, details, due, rule, subtasks, list name) with a **Done** button and
  subtask select(s). Without a channel a due reminder is marked `failed` (`no_channel`).
- **Done** completes the occurrence (and a one-time to-do) and **deletes the reminder message**. The
  reply everywhere is "✅ Checked off **title**." plus " Next: <timestamp>" for repeating to-dos
  (`render.done_text`). `/todo show` → Done turns the message into just that line.
- **Non-assignees confirm** (D67): anyone who isn't an assignee (owners and Manage Server included)
  gets "**title** is assigned to @A and @B, not you. Check it off anyway?" before checking off, in all
  four places. Ticking subtasks never asks. `views/confirm.py` (`must_confirm`, `CheckOffConfirmView`).
- **Undo** (D60–D69): every check-off reply has an Undo button (`/todo upcoming`: an "Undo a
  check-off…" select). The check-off services return `CheckedOff(todo, undo: UndoToken)`; the token
  (previous occurrence status, the pending follow-up's id, reset subtask ticks) lives only in the
  view's memory (2-hour timeout, gone after a restart). `services/undo.py` re-checks everything:
  only the person who checked it off, within 2 h (`UNDO_WINDOW`), while they may still check off.
  It restores the to-do/occurrence, cancels the follow-up an early check-off created, restores ticks
  for subtasks that still exist and are unticked. A reminder that was up is marked `sent` again with
  `sent_at = now` and no message, and the bot re-posts it with pings (`SidequestClient.repost` →
  `Scheduler.deliver`). Refused when the follow-up is no longer pending (sent → "already went out",
  done → "undo the later check-off first", cancelled by an edit → "changed"), or on a title clash.
- Checking off a pending occurrence early (`/todo upcoming`, `/todo done`) means that reminder never
  posts; for repeating to-dos the one after it is scheduled.
- A new occurrence firing while the previous reminder is unchecked deletes it and marks it `missed`.
  After downtime: at most one catch-up reminder per to-do, marked late ("Late — was due …", > 2 min).

### Limits
Title ≤ 200 · details ≤ 4000 · subtask title ≤ 100 · subtasks ≤ 50 · assignees ≤ 10 · times per rule
≤ 12 · list name ≤ 50 · lists ≤ 25/server · collaborators ≤ 25/list. Discord: 25 options per select
(subtasks use two selects), labels ≤ 100, embeds ≤ 6000 total (description ≤ 4096).

---

## 5. Code conventions

- Python 3.12, full type hints, ruff lint + format, line length 100. LF line endings (`.gitattributes`).
- All datetimes are timezone-aware UTC internally. "Now" comes only from a `Clock` (tests use
  `tests.support.clock.FixedClock`). Business timestamps come from the clock, not DB `now()`.
- Service DTOs, inputs, `Actor`, `Outcome` and effects are strict, frozen pydantic models
  (`services.model.StrictModel`): keyword arguments only, no coercion. `TodoPatch` uses `model_fields_set`.
- ORM relationships are `lazy="raise"`: load what you need with `selectinload`/`joinedload`
  (`_common.todo_load()` for anything that builds a `TodoView`).
- User text in bot output is escaped; messages set explicit `allowed_mentions` (users on reminders only,
  none elsewhere). Logging via `logging`, never `print`.
- Command options are added via factory functions (`build_todo_group()` etc.), not class-based groups.
  `todo`/`list` options are strings with autocomplete; the `list` option is `list_` in Python with
  `@app_commands.rename`.
- Code comments mention `BRIEF §…`, `D<n>` and `S<n>`: those point to `docs/claude/archive/initial-release/`. The live
  decisions are summarised in §6.

---

## 6. Decisions still in force

Numbered as in the archived brief; superseded ones are left out. New decisions continue from D60
and are added here and in the feature's brief.

| ID | Decision |
|---|---|
| D1 | 24h input; points in time as Discord timestamps (12h/24h per viewer is accepted). |
| D4 | Subtasks are plain checklist items; reset per occurrence on repeating to-dos. |
| D6 | One reminder channel per server, set by Manage Server. |
| D7 | A new occurrence replaces an unchecked previous reminder (deleted, marked missed). |
| D8 | Completed to-dos are kept as history; optional retention. |
| D9 | Optional details ≤ 4000 chars via a modal, shown in reminders. |
| D10–D15 | Postgres 17 · `Intents.none()` · discord.py 2.7 · SQLAlchemy async + Alembic · DB is the schedule (poll ≤ 60 s + in-process wake) · hand-written pure recurrence engine. |
| D17/D18 | No date-only to-dos; a time without a date is the next one coming; past is rejected. |
| D21/D22 | Monthly by n-th weekday and by day (with last-day fallback); several times per day. |
| D23–D25 | Done with unticked subtasks is fine · server to-dos use the creator's zone unless overridden · fallback zone `DEFAULT_TIMEZONE` (UTC), mentioned once. |
| D27–D31 | Ephemeral replies (`/todo list post:true` is public) · English only · ≤ 50 subtasks in two selects · arm64 · Python 3.12. |
| D32/D33 | `SYNC_GLOBAL` + `SYNC_GUILD_IDS` (dev bot: `SYNC_GLOBAL=false`) · env file at `configs/.env`. |
| D34 | Strict, frozen pydantic service models. |
| D36 | Manage Server can unset the reminder channel (with a count + confirm). |
| D37 | One check-off wording everywhere; `/todo show` → Done leaves only that line. |
| D38 | Watchdog restarts the bot when the heartbeat stalls (3 min; 5 min at start). |
| D39 | Details render markdown; titles are fully escaped. |
| D40–D53 | Server-only, no DMs · named lists (≤ 25) · ownerless Default List · unique list names and open titles (case-insensitive) · per-user default list · owners, collaborators, transfer · list delete asks delete/move/cancel · `/todo move` · one list per view · permissions table in §4. |
| D54–D59 | Weekly `every` 1–52 and `start` (anchored to the soonest reminder when omitted), Mon–Sun weeks, JSON keys only when non-default (no migration). |
| D60–D62 | Undo on every check-off reply, for 2 hours, in memory only (not after a restart); only the person who checked it off, while they may still check off on that list. |
| D63–D66 | Undo restores the state from before (status, follow-up cancelled, subtask ticks); a reminder that was up is re-posted with pings; refused when it would clash with what happened since; no storage change (`UndoToken`). |
| D67 | Non-assignees (everyone, incl. owners and Manage Server) confirm before checking off; subtasks never ask. |
| D68/D69 | Undo wording ("↩️ Undone: **title** is open again."); `/todo upcoming` gets an undo select (newest first, any order). |

**Out of scope for now:** web frontend · snooze · role assignees · every N days / N months · start dates
for daily/monthly rules · date-only to-dos · per-server default timezone · localisation · digests.

---

## 7. Checks and testing

- `ruff check .` and `ruff format --check .`
- `pytest tests/unit`
- Integration tests need the test Postgres:
  `docker compose -f compose.test.yaml up -d`, then
  `TEST_DATABASE_URL=postgresql+asyncpg://sidequest:sidequest@localhost:55432/sidequest_test pytest`.
  Without the variable they skip with a message. If Docker isn't available, say so; never fake it.
- After model changes: `alembic check` (no drift between models and migrations).
- Local dev: `.venv` with Python 3.12 (`py -3.12 -m venv .venv`, `pip install -r requirements-dev.txt`,
  `pip install --no-deps -e .`).
- Don't build the Docker image to "verify" (Tim's rule). Claude can't use Discord: every feature that
  touches Discord ends with a **manual test checklist** for Tim's dev bot.

## 8. Operating the bot

`docs/claude/RUNBOOK.md` covers Pi setup, the Developer Portal, `configs/.env`, `update.sh` (backup,
build, migrate), health and the watchdog, logs, backups and `scripts/restore-backup.sh`, retention, the
dev bot, and per-upgrade notes. Add an "Upgrading to …" note there for any feature with a migration
or a rollback risk.
