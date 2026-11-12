# Progress

> Updated by Claude (Opus 5.5) at the end of every session.

## Status

| Seg | Title | Status | Branch |
|---|---|---|---|
| S1 | Foundation | ✅ done | `claude/s1-foundation` |
| S2 | Data model | ✅ done | `claude/s2-data-model` |
| S3 | Time & recurrence | ✅ done | `claude/s3-time-and-recurrence` |
| S4 | Services | ✅ done | `claude/s4-services` |
| S5 | Commands | ✅ done | `claude/s5-commands` |
| S6 | Reminders | ✅ done | `claude/s6-reminders` |
| S7 | Ops & hardening | ✅ done | `claude/s7-ops` |
| S8 | Server lists (no personal lists/DMs; collaborators) | 👀 waiting for review | `claude/s8-server-lists` |

Legend: ⬜ todo · ⏭️ next · 🔨 in progress · 👀 waiting for Tim's review/commit · ✅ done

## Before S1 (Tim)
- [x] Review assumptions A1–A14 (done 2026-11-10 → decisions D17–D29).
- [x] A9: Pi confirmed 64-bit (`aarch64` / `arm64`) → D30.
- [ ] Create a **dev** Discord application (separate from production) with a test server; note its token and the test server ID for `SYNC_GUILD_IDS`.
- [ ] In the Developer Portal → Installation: enable **Guild Install** (scopes `applications.commands`, `bot`; permissions View Channel, Send Messages, Embed Links). ~~and **User Install**~~ Since S8 (D40): **untick User Install**. Leave all privileged intents off.

## Future work (Tim's notes, not scheduled)

- ~~**Commands don't work in DMs**~~ Closed by S8 (D40): Sidequest has no DMs any more, so this and the DM verification are obsolete.

## Handoff log

### 2026-11-10 — Brief written
- Brief, workflow and segment docs created. No code yet.
- Next: S1. S2 and S3 may run in either order after S1.
- Same day: Tim reviewed the assumptions. Changes vs. the first draft: no date-only to-dos; monthly day-of-month rules (with last-day fallback); default timezone UTC; English-only input; 50 subtasks (two selects). Pi confirmed 64-bit (D30); no open assumptions. Root `CLAUDE.md` added.

### 2026-11-10 — S1 Foundation built (done)
- All 8 checklist items done on `claude/s1-foundation`. Uncommitted.
- **Checks:** `ruff check .` clean · `ruff format --check .` clean · `pytest tests/unit`: 24 passed. Migrations smoke-tested against `compose.test.yaml` Postgres: `sidequest migrate` and bare `alembic current` both reach `0001`.
- **Not verified by Claude:** `docker compose up --build` and anything in Discord (Tim's global rule: no build verification). See the manual checklist below.
- **Deviations / decisions:**
  - Python **3.12**, not 3.13 (D31, Tim). BRIEF, WORKFLOW and the S1 doc are updated. Local dev uses `.venv` (Python 3.12): `py -3.12 -m venv .venv`, `pip install -r requirements-dev.txt`, `pip install --no-deps -e .`.
  - `scripts/compile-requirements.sh` adds `--no-emit-index-url` (Tim's global rule) and handles Git Bash path conversion on Windows.
  - `/sidequest about` lives in `bot/commands/about.py` as `SidequestGroup`; it's not in the BRIEF §5.3 layout. Later `/sidequest` subcommands can go on this group.
  - `core/clock.py` added early (a minimal `Clock.now()`), because uptime needs "now". S3 may extend it.
  - Alembic: `alembic.ini` is read from the working directory (override with `ALEMBIC_CONFIG`). The URL comes from `DATABASE_URL` via `config.DatabaseSettings`, so the bare `alembic` CLI needs no bot token. `sidequest migrate` loads the full `Settings` and therefore needs `DISCORD_TOKEN`. New revisions: `alembic revision --rev-id 0002 -m "..."` (file template `<rev>_<slug>.py`).
  - `env_ignore_empty=True`: empty env values count as unset (e.g. `SYNC_GUILD_IDS=`).
  - `DEV_GUILD_ID` → `SYNC_GLOBAL` + `SYNC_GUILD_IDS` (D32, Tim). `SYNC_GLOBAL=true` (default, production): global sync, and the listed guilds get their guild commands deleted, so switching a dev bot back never leaves duplicates. `SYNC_GLOBAL=false` (dev): commands only in the listed guilds (instant), global cleared, no DMs; rejected with an empty list. A failed guild sync logs a warning; startup continues. Tim's `configs/.env` got `SYNC_GLOBAL=false` to keep the behaviour it had.
  - Env file moved to `configs/.env` (D33, Tim). Both compose services load it via `env_file` (so the db container also sees the bot token in its env, which is harmless but worth knowing). `configs/.env.example` is the template; `.gitignore` uses `configs/*` + `!configs/.env.example` so only the template is tracked.
  - ruff excludes `docs/`, because ruff format was reformatting Python blocks inside the segment docs.
  - `compose.yaml` uses `env_file` with `required: false`, which needs Docker Compose ≥ 2.24 on the Pi.
- **Manual checklist (Tim):**
  1. `git add --chmod=+x update.sh scripts/compile-requirements.sh`
  2. `cp configs/.env.example configs/.env` and fill in the token, the Postgres password (in both places) and, on the dev bot, `SYNC_GLOBAL=false` + `SYNC_GUILD_IDS`.
  3. `docker compose up --build`: db healthy, log shows "Applying database migrations", dev bot: "Server-only mode: cleared global commands" + "Synced command(s) to guild …" per listed guild (production: "Synced 1 global command(s)"), "Logged in as …".
  4. `/sidequest about` in a listed guild (dev) or any server + DM (production): ephemeral reply, "Running since" shows a relative timestamp, and "Deployed" says unknown (no `configs/git.env` locally).
  5. On the Pi: `bash update.sh` → bot online, `/sidequest about` shows commit, branch and deploy time; run it a second time → `backups/backup-*.sql.gz` appears.
- Done: Tim committed S1 as `30f90f4` and deployed on the Pi. Bot online, `/sidequest about` shows commit/branch/deploy time, and the second `update.sh` run wrote a backup. First deploy failed until `DATABASE_URL` and `POSTGRES_PASSWORD` matched; Postgres only applies `POSTGRES_PASSWORD` when the volume is first created (worth a line in the S7 runbook).
- Next: S2 (S3 may go first instead; they are independent).

### 2026-11-10 — S2 Data model built (done)
- All 4 checklist items done on `claude/s2-data-model`. Uncommitted.
- **Checks:** `ruff check .` clean · `ruff format --check .` clean · `pytest tests` with `TEST_DATABASE_URL` against `compose.test.yaml`: **57 passed** (unit + 20 integration). Without the env var the integration tests skip with a clear message. `alembic check` reports no drift between models and migrations.
- **Files:** `core/enums.py` (new), `db/models.py` (new), `db/base.py`, `migrations/env.py`, `migrations/versions/0002_schema.py` (new), `alembic.ini`, `tests/integration/{conftest,test_migrations,test_schema}.py` (new).
- **Deviations / decisions:**
  - Migration is revision **`0002`** (`0002_schema.py`), not `0001_initial`: the empty `0001` is already applied on the Pi, so filling it in would never run there.
  - Enums `Scope`, `TodoKind`, `TodoStatus`, `OccurrenceStatus` live in `sidequest.core.enums` (StrEnum) and are re-exported from `sidequest.db.models`. Columns store the enum **values** (`'server'`, not `'SERVER'`) as `VARCHAR(16)` + CHECK.
  - All relationships use **`lazy="raise"`** + `passive_deletes=True`. S4+ must load `Todo.assignees/subtasks/occurrences` (and `.todo` on children) explicitly with `selectinload`/`joinedload`. New, unflushed objects can take children in the constructor. Deleting a `Todo` via the ORM works without loading children (DB cascade); tested.
  - `Todo.recurrence` is `JSONB(none_as_null=True)`. Without it SQLAlchemy writes Python `None` as JSON `'null'`, which slipped past the `recurring_rule` CHECK (caught by the tests).
  - `Base.type_annotation_map` maps `datetime` → `TIMESTAMPTZ`, so every `Mapped[datetime]` column is timezone-aware.
  - Extra index `ix_occurrences_todo_id` (not in the segment doc): the partial unique indexes only cover `pending`/`sent`, and the FK cascade and per-to-do lookups need a plain index.
  - `created_at`/`updated_at` use DB `now()` defaults (as the segment doc says), not `Clock`. Business timestamps (`completed_at`, `sent_at`, …) must still come from `Clock`.
  - The integration conftest drops and recreates the `public` schema once per run, and refuses (fails) unless the database name ends in `_test`. Each test runs in a rolled-back transaction (`join_transaction_mode="create_savepoint"`).
  - `alembic.ini` gained `path_separator = os` (silences an Alembic deprecation warning).
- **Run integration tests:** `docker compose -f compose.test.yaml up -d`, then `TEST_DATABASE_URL=postgresql+asyncpg://sidequest:sidequest@localhost:55432/sidequest_test pytest`.
- **Manual check (Tim):** on the Pi, `bash update.sh` → log shows "Running upgrade 0001 -> 0002"; the bot still starts and `/sidequest about` still works. No Discord-facing changes in S2.
- Same session: descriptions added to the enums in `core/enums.py` (docstrings per value).
- Done: Tim committed S2 as `4f7e7aa` and deployed on the Pi; migration `0002` applied and the bot works.
- Next: S3 Time & recurrence.

### 2026-11-11 — S3 Time & recurrence built (waiting for review)
- All modules from the segment doc done on `claude/s3-time-and-recurrence`. Uncommitted.
- **Checks:** `ruff check .` clean · `ruff format --check .` clean · `pytest tests/unit`: **204 passed** (93 for timeparse/tz/clock/discord_time, the recurrence table, the layering test now also covers `sidequest.db`). Integration tests were not re-run: S3 touches no DB code.
- **Files:** `core/{clock,discord_time,enums}.py` (changed), `core/{errors,limits,tz,timeparse,recurrence}.py` (new), `bot/client.py` + `tests/unit/test_command_sync.py` (`Clock()` → `SystemClock()`), `tests/unit/test_layering.py` (core also may not import `sidequest.db`), `tests/__init__.py` + `tests/support/{__init__,clock}.py` (new), `tests/unit/{test_timeparse,test_tz,test_clock_and_discord_time,test_recurrence}.py` (new), `pyproject.toml` + lockfiles (`pydantic` is now a direct dependency; the pins didn't change, only the `# via` comments).
- **Deviations / decisions:**
  - Branch is `claude/s3-time-and-recurrence` (the segment doc said `claude/s3-time-recurrence`).
  - `Clock` is now a `Protocol`; `SystemClock` is the production clock. Code that needs "now" takes a `Clock`.
  - The test clock `FixedClock(now)` (`set`, `advance`) lives in **`tests/support/clock.py`** (Tim: keep test-only code out of the package). Import it as `from tests.support.clock import FixedClock`; this works because `tests/` and `tests/support/` are packages, pytest has `pythonpath = ["."]`, and ruff treats `tests` as first-party. Shared test helpers for S4–S6 (e.g. a `FakeNotifier`) belong in `tests/support/` too.
  - `Weekday` (`"mon"`…`"sun"`, `.index` Monday = 0, `.full_name`, `from_index`) lives in `core/enums.py` next to the other shared enums.
  - Rule models are frozen pydantic models; `times`/`weekdays` are **tuples**, sorted and deduplicated on validation (JSON still uses lists). Both `from_json(...)` and direct construction (`DailyRule(times=[...])`) raise `InvalidRule`, never pydantic's `ValidationError`. Python construction accepts `time` objects or `"HH:MM"` strings. `week`/`day` are strict ints (a JSON `true` is rejected).
  - `to_json`/`from_json` are module functions (`RecurrenceRule` is an `Annotated` union, so it can't carry methods).
  - `next_occurrence` sorts the resolved instants per day: on a spring-forward day 02:30 becomes 03:30 and can land after a later wall-clock time or on the same instant; duplicates collapse to one occurrence.
  - `describe` for days 29–31 puts the fallback note right after the day: "Every month on the 31st (or the last day of shorter months) at 09:00 (UTC)", which reads better than appending it after the timezone.
  - `resolve_local` relies on `fold=0`: zoneinfo applies the pre-transition offset, which shifts a gap time forward by the gap and picks the first instance of an ambiguous time. That covers both DST rules without special cases.
  - `resolve_due` with time only: "still ahead" means strictly later than `now`; otherwise tomorrow. The `InPast` message shows the moment as a Discord timestamp.
  - Parsing extras: `parse_weekdays` also accepts `tues`, `weds`, `thur`, `thurs` and the word `and`; `parse_month_day` raises `InvalidRule`; a two-digit year gets its own message ("Write the year in full"). `search_zones` with an empty query returns the first 25 names alphabetically, and `posix/`, `right/`, `Factory`, `localtime`, `posixrules` are never offered.
  - `core/limits.py` also holds Discord's limits (select options 25, label 100, embed description 4096, embeds total 6000).
- **Manual check (Tim):** none in Discord; S3 is pure code. `bash update.sh` on the Pi should behave as before (no migration).
- Done: Tim committed S3 as `997cce7`.
- Next: S4 Services.

### 2026-11-11 — S4 Services built (waiting for review)
- All 5 checklist items done on `claude/s4-services`. Uncommitted.
- **Checks:** `ruff check .` clean · `ruff format --check .` clean · `pytest` with `TEST_DATABASE_URL`: **318 passed** (after D34) (60 new permission table tests, 26 new service integration tests incl. two concurrent `claim_due` calls on separate connections) · `alembic check`: no drift.
- **Files:** `services/{__init__,actor,effects,uow,dto,permissions,_common,settings,todos,subtasks,occurrences}.py` (new), `core/errors.py` (NotFound, Forbidden, ReminderChannelNotSet, LimitExceeded, InvalidOperation), `db/models.py` (`eager_defaults` on the timestamp mixin), `tests/integration/conftest.py` (fixtures `clock`, `uow`, `committed_sessions`; `START` = Mon 2030-01-07 09:00 UTC), `tests/unit/test_permissions.py`, `tests/integration/test_services_{todos,occurrences,subtasks}.py` (new).
- **How S5/S6 call services:** `uows = UowFactory(sessionmaker, SystemClock(), settings.default_timezone)`; per interaction `async with uows() as uow: out = await todos.complete(uow, actor, todo_id)`. Mutations return `Outcome(value, effects, changed_schedule)`: run `out.effects` (ignore "message not found") and wake the scheduler when `changed_schedule`. Errors are `SidequestError` subclasses with a user-safe `.message`.
- **Deviations / decisions:**
  - Pattern: functions take a **`Uow`** (session + clock + `default_timezone`) first, then the `Actor`; each commits itself. `UowFactory` opens one per request. Tests build `Uow(session, FixedClock(...))` directly.
  - `create_once` takes **`due: DueInput(date, time)`** (raw user input), not a resolved `Untimed|Timed`. The service resolves the timezone first (override → user → default) and then applies D17/D18, so callers never resolve times in the wrong zone. `edit` uses the same `DueInput` in `TodoPatch(title, details, due, rule, timezone)`.
  - `list` is named **`todos.list_todos`** (a module-level `list` would shadow the builtin).
  - Locking: every write locks the to-do row (`FOR UPDATE`) first; `claim_due` locks to-do + occurrence with `SKIP LOCKED`. So a user action and the scheduler never interleave on one to-do, and two schedulers never claim the same row (tested).
  - Recurring `complete`/`complete_occurrence` on the **sent** reminder: the next pending already exists (made at claim time), so nothing new is materialized. Completing the **pending** one early materializes the one after it (`after = max(due_at, now)`).
  - `claim_due` resets subtasks only when it actually closes a previous sent reminder as missed. Ticks made early for the upcoming occurrence survive (BRIEF §4.4: reset when an occurrence is closed).
  - `edit` of a repeating to-do keeps its sent reminder (it is still the current occurrence) and only replaces the pending one. Changing only the timezone of a timed one-time to-do keeps the wall-clock time and re-resolves it in the new zone (`InPast` if that moment has passed).
  - `attach_message` returns a `DeleteMessage` for the just-posted message if the occurrence was checked off or cancelled while it was being posted.
  - `mark_failed` reasons: `FAILURE_DM_CLOSED` (also sets `dm_failed_at`), `FAILURE_NO_CHANNEL`, `FAILURE_CHANNEL_UNAVAILABLE`. `DueReminder.channel_id` is None if a server never set a channel.
  - `todos.get` shows done to-dos (history) but `NotFound` for deleted ones. Changing a done to-do raises `InvalidOperation("already done")`.
  - `autocomplete` labels personal to-dos `(personal) …` when both lists are searched; labels are cut to 100 chars.
  - Settings functions return plain values, not `Outcome` (they have no effects).
  - `TodoView.can_edit` tells the UI whether to offer edit buttons for that actor.
  - `eager_defaults` on `_Timestamps`: `created_at` is fetched via `RETURNING` on insert, so views can read it after a flush without an async lazy load. No migration change.
- **D34 (same session, Tim):** service models are strict + frozen pydantic (`services/model.py: StrictModel`, also `extra="forbid"`). Converted: all DTOs in `services/dto.py`, `TodoPatch` (moved from `todos.py` into `dto.py`), `Actor`, `Outcome`, `DeleteMessage`. Construct them with **keyword arguments only** (`Outcome(value=view)`, `Actor(user_id=…, guild_id=…, can_manage_guild=…, origin=…)`). `Uow` stays a dataclass: it holds a session and a clock, not data. `TodoPatch` uses `model_fields_set`: `TodoPatch(details=None)` clears, leaving `details` out keeps them. Strict means no coercion: e.g. `DueInput(time="10:00")` fails; S5 must parse with `core.timeparse` first. +8 tests (`tests/unit/test_service_models.py`, one edit test) → **318 passed**.
- **Manual check (Tim):** none in Discord; S4 adds no commands. `bash update.sh` on the Pi should behave as before (no migration).
- Done: Tim committed S4 as `aadcf55`.
- Next: S5 Commands.

### 2026-11-11 — S5 Commands built
- All 7 checklist items done on `claude/s5-commands`. Uncommitted.
- **Checks:** `ruff check .` clean · `ruff format --check .` clean · `pytest` with `TEST_DATABASE_URL`: **388 passed** (+70: render, options, adapter, sync hashing, autocomplete). Nothing tested in Discord itself (see the manual checklist).
- **Files:** new: `bot/{adapter,errors,render,autocomplete,options}.py`, `bot/commands/{common,todo,todo_list,todo_view,todo_manage,todo_edit,repeat,subtask,settings,admin}.py`, `bot/views/{__init__,base,modals,show,upcoming,listing,assign,confirm}.py`, `scheduler/{__init__,signal}.py`, `services/meta.py`, `tests/unit/test_{render,options,adapter}.py`. Changed: `bot/client.py`, `bot/commands/about.py`, `services/todos.py`, `tests/unit/test_command_sync.py`, `tests/integration/test_services_todos.py`.
- **How it fits together:** `SidequestClient(settings, clock, deps)`; `BotDeps(uows, signal, command_hashes, engine)` sits on the client, and commands reach it via `adapter.deps(interaction)`. Command pattern: `defer` → `actor_from` → service call(s) + `collect_notes` in one `uows()` block → `apply(interaction, outcome)` (effects + scheduler wake) → `reply(...)`. Errors are raised, never caught: `tree.error(report_error)`, `BaseView.on_error` and `BaseModal.on_error` show `SidequestError.message` ephemerally and log everything else with a traceback.
- **For S6:** `scheduler/signal.py` has `ScheduleSignal.wake()` and `await wait(seconds) -> bool` (in-process `asyncio.Event`); the loop should use `client.deps.signal`. `render.todo_embed(todo)` and `render.subtask_option_pages(todo)` are the shared reminder renderers (kept within 6000 chars, 1–2 selects). `adapter.run_effects(client, effects)` executes `DeleteMessage`.
- **Deviations / decisions:**
  - `/sidequest channel` is a subcommand of the existing `/sidequest` group. Discord only allows install contexts and default permissions on top-level commands, so it can't be guild-only or hidden from non-admins. It checks at runtime instead: guild-installed, Manage Server (or Administrator), text/news channel. Non-admins see it but get a clear error. Alternative if Tim prefers: a separate top-level command with `default_permissions(manage_guild=True)`.
  - Commands are built by factory functions (`build_todo_group()`, `add_command()`, …) that create fresh command objects, not class-based groups. Reason: discord.py's `Group` only collects commands from the class's own `__dict__`, so one group can't be spread over several files. Fresh objects also let tests create several clients.
  - `todos.autocomplete` now returns `(id, title, scope)` instead of `(id, label)`. The adapter builds the `[S]`/`[P]` label and cuts it to 100 chars (`render.autocomplete_label`). New integration test.
  - `todo`/`subtask` options are **string** options with autocomplete (value = id as text). Discord's client only allows digits in integer options, so typing a title to search would be impossible. Free text that isn't an id → "Pick a to-do from the list that appears while you type."
  - `/todo edit`: for a timed one-time to-do, a `date` without `time` keeps the current wall-clock time (in the new timezone if one is given). Rule parts are checked against the rule type (`options.edited_rule`); switching type is refused with "delete the to-do and add it again".
  - `/todo upcoming` without `scope` in a server asks with buttons: Server list / Personal list / Both (D35, Tim; `views/upcoming.py: ScopePickView`). The picked view replaces the prompt in the same message. In DMs it shows the personal list directly.
  - Create commands validate pure inputs (time/date format, timezone, scope, the rule) **before** a `details:True` modal opens, so a typo doesn't throw away typed details. `today`/`tomorrow` resolve in the to-do's timezone (override → user → default).
  - `/todo list post:true` is deferred publicly; one-time notes go in a separate ephemeral follow-up. Anyone can page a public list (it re-queries the same server list with the presser's actor).
  - Details text keeps its markdown (only mentions are escaped); titles and subtasks have markdown and mentions escaped. All command responses use `AllowedMentions.none()`.
  - Notes (timezone hint, DM failure) are collected after the service call, so a failed command doesn't use up the one-time hint. Autocomplete never consumes them; `/sidequest about` doesn't show them.
  - Select labels can't render Discord timestamps (C5), so the upcoming select uses "N. title" matching the numbered embed rows; subtask selects and embed lines are numbered the same way.
  - Command sync hash: SHA-256 of the canonical JSON of the global payload, stored in `app_meta['command_hash']` via `services/meta.py`. Server-only mode hashes the empty global payload, so global commands are cleared once, not on every start. Guild syncs and cleanup always run. A hash read/write failure logs a warning and falls back to syncing.
  - `ScheduleSignal` was created now (BRIEF §5.3 `scheduler/signal.py`) so S5 can wake the scheduler; S6 owns the loop.
- **Manual test checklist (Tim, dev bot with `SYNC_GLOBAL=false`):**
  - [x] Startup log: "Server-only mode: cleared global commands" on the first start, "Global commands unchanged; skipped sync" on the second; guild sync both times.
  - [x] `/sidequest channel` as admin posts a confirmation in that channel; a non-admin is refused; a channel the bot can't post in gives the permissions hint.
  - [x] `/settings timezone` autocomplete finds `Europe/Amsterdam`; setting it works; without an argument it shows the current one.
  - [x] `/todo add` untimed, time-only, explicit `today` + time, date+time; date-only rejected; past time rejected; `9pm` rejected with the 24h hint.
  - [x] Server timed to-do before `/sidequest channel` is set → clear error.
  - [x] `/todo repeat monthly-day day:31` → reply notes the last-day fallback; next occurrence right.
  - [x] `/todo repeat weekly days:mon,thu times:12:00` → description reads correctly, next-occurrence timestamp right.
  - [x] 30 subtasks (`/todo subtask add` with `;`) → two selects in `/todo show`; ticking updates the embed; no embed error.
  - [x] `/todo add details:True` opens a modal; multi-line text shows in `/todo show`; the "Edit details" button and `/todo details` prefill it; emptying it removes the details.
  - [x] ~~Personal to-do created in a server is visible in DMs with the bot, and not to another user.~~ Obsolete (S8, D40).
  - [x] `/todo upcoming` in a server without `scope` → Server / Personal / Both buttons; each shows the right items. In DMs → personal list straight away.
  - [x] `/todo upcoming` → check one off early → it disappears and the list refreshes.
  - [x] `/todo assign` (select prefilled); a non-assignee without Manage Server can't edit, assign or delete.
  - [x] `/todo list` with >10 to-dos pages with Prev/Next; `post:true` posts publicly; `post:true scope:Personal` is refused.
  - [x] `/todo edit` title / time / `times`; an option for another rule type gives the "delete and add again" message.
  - [x] `/todo delete` → Delete removes it, Cancel keeps it.
  - [x] Autocomplete on `todo` options is fast and shows `[S]` / `[P]`.
  - [x] A user without a timezone sees the one-time UTC hint on their first command.
  - **S6 reminders** (added 2026-11-11):
  - [x] Server to-do at now+2 min with two assignees → posted in the reminder channel, both pinged (nobody else, no roles); the embed shows details, due time, subtasks.
  - [x] Someone who isn't an assignee can press Done (D3) → ephemeral "Checked off", the reminder message disappears.
  - [x] Personal timed to-do → arrives as a DM with a working Done button.
  - [x] Daily to-do left unchecked → the next occurrence deletes the old message and posts a new one.
  - [x] Subtask select on a reminder ticks items and the embed updates; with 30 subtasks each select only changes its own page; on a repeating to-do they're reset for the next occurrence.
  - [x] `/todo upcoming` → check off before it's due → that reminder never arrives.
  - [x] `/todo delete` while its reminder is up → the reminder message is deleted.
  - [x] Restart the bot (`docker compose restart bot`) → an old reminder's Done button and select still work.
  - [x] Stop the bot past a due time, start it → one reminder, marked "Late — was due …" (a daily to-do down for several days: still only one).
  - [x] Turn off "Allow DMs from server members" → a personal reminder fails → warning on the next command.
  - [x] ~~**DM verification (BRIEF §5.4, postponed until DMs work — see Future work):** a test account that has the app user-installed and shares **no** server with the bot creates a personal timed to-do in DMs. Does the reminder DM arrive? Tell Claude the answer so it can be recorded.~~ Obsolete (S8, D40).
  - [x] Heartbeat: `docker compose exec bot cat /tmp/sidequest-heartbeat` shows a recent UTC time.
  - [x] All times show as Discord timestamps.
  - **D37 check-off wording:**
  - [x] `/todo show` → Done on a one-time to-do: the embed and buttons disappear, only "✅ Checked off **title**." remains.
  - [x] Same on a daily to-do: "✅ Checked off **title**. Next: <timestamp>".
  - [x] `/todo done`, `/todo upcoming` and a reminder's Done button use the same wording.
  - **Edit details refresh:**
  - [x] `/todo show` → Edit details → save: the same message now shows the new details and "📝 Details saved …"; the buttons still work. Emptying the box removes the details from the message.
  - **D36 unset reminder channel:**
  - [x] `/sidequest channel clear:True` as admin → warning with the number of timed server to-dos + Unset channel / Cancel. Cancel keeps it; Unset clears it.
  - [x] After unsetting: a timed server to-do is refused with the "set a reminder channel" error; a due server reminder isn't posted (marked failed); an earlier reminder's Done still works.
  - [x] `clear:True` with a channel → error; `clear:True` when none is set → "no reminder channel set"; non-admin → refused.
- Done: Tim committed S5 as `4cbcc59`. Tim hasn't run the checklist above yet; S5 and S6 get tested together after S6.
- Next: S6 Reminders. **S6: add your manual checks to the open S5 checklist above** (Tim's choice, one combined test pass) instead of starting a separate list.

### 2026-11-11 — S6 Reminders built
- All checklist items done on `claude/s6-reminders`, except the DM verification, which needs Discord (on the checklist above). Uncommitted.
- **Checks:** `ruff check .` clean · `ruff format --check .` clean · `pytest` with `TEST_DATABASE_URL`: **414 passed** (+26: 9 scheduler loop tests with `FakeNotifier` + real Postgres, 7 for the new services, 9 reminder render/view tests, layering now also covers `scheduler`). Nothing tested in Discord itself.
- **Files:** new: `scheduler/{loop,notifier}.py`, `bot/notifier.py`, `bot/views/reminder.py`, `tests/support/notifier.py`, `tests/integration/test_{scheduler,services_reminders}.py`, `tests/unit/test_reminder_render.py`. Changed: `services/occurrences.py` (`tick_subtasks`, `is_live`, failure reasons), `bot/render.py` (`reminder_embed`, `reminder_pings`), `bot/client.py` (dynamic items, starts/stops the scheduler), `bot/adapter.py` (`BotDeps.run_scheduler`), `tests/unit/{test_command_sync,test_layering}.py`, `docs/claude/BRIEF.md` §5.4.
- **How it fits together:** `setup_hook` registers `DoneButton`/`SubtaskSelect` (`add_dynamic_items`), syncs commands, then starts `Scheduler(uows, DiscordNotifier(client), signal, clock).run()` as a background task; `close()` cancels it. The scheduler only knows the `Notifier` protocol (`post` → `Posted | Failed`, `execute(effects)`), so it has no Discord imports (enforced by the layering test).
- **Deviations / decisions:**
  - **Recovery runs every iteration**, not only at startup (still only for reminders claimed > 60 s ago). Reason: after a crash, Docker restarts the bot within seconds, so a startup-only check with a 60 s threshold would skip exactly the reminders the crash left behind. The loop is sequential, so nothing of its own is in flight during recovery.
  - Sleep is clamped to **1–60 s** when nothing was claimed: an occurrence that is due but locked by a user's edit (`SKIP LOCKED`) would otherwise make the loop spin.
  - Failure reasons: `no_channel`, `forbidden`, `channel_gone`, `dm_closed`, `error` (any other exception; details in the log). S4's unused `channel_unavailable` is replaced by `forbidden` + `channel_gone`. Transient Discord errors are not retried beyond what discord.py does: the occurrence is marked `failed`.
  - If a to-do is deleted while its reminder is being posted, `attach_message` raises `NotFound` and the loop deletes the just-posted message.
  - **Heartbeat:** `<tempdir>/sidequest-heartbeat` (`/tmp/…` in the container), ISO UTC time, written only after a **successful** iteration, so a broken DB also makes it go stale. Not configurable yet; S7 can add a setting if needed.
  - Reminder components build their `Actor` from `interaction.guild_id` directly (`views/reminder.py: reminder_actor`), not `adapter.actor_from`: only the bot posts reminders, so a reminder in a server proves the bot is installed there, and a component interaction may not carry the guild install owner that `is_guild_integration()` checks.
  - Done / select on a stale reminder (already checked off, missed, or the to-do deleted): an ephemeral error, and the message is deleted only if `occurrences.is_live` says the reminder is over. A "not visible to you" `NotFound` never deletes it.
  - The subtask select takes `within` from the options on the message itself (rebuilt by discord.py from the message), so a subtask added after posting can't be unticked by a select that doesn't show it. After a tick the message is re-rendered from the current to-do, so new subtasks appear.
  - DynamicItem callbacks are wrapped in `try/except → report_error`, because discord.py only logs exceptions from dynamic items and the user would see nothing.
  - DM verification (user-install without a shared server) is not done: Claude can't use Discord. Recorded as open in BRIEF §5.4 and on the checklist; the code handles both answers.
- **Manual check (Tim):** the S6 items are added to the open S5 checklist above (one combined test pass, as agreed).
- Done: Tim committed S6 as `ba5c123`. The combined S5+S6 manual test pass (incl. the DM verification) is still open.
- Next: S7 Ops & hardening.
- 2026-11-11: Tim ran the combined S5+S6 (+D36, D37, details refresh) manual pass: all items pass except "personal to-do visible in DMs", which is blocked by commands not working in DMs (see Future work). The DM verification is postponed (Tim): it needs working DM commands first.
- Same day, Tim: unsetting the reminder channel must be possible → **D36**, built right away on `claude/s6-reminders` (Tim asked; uncommitted):
  - `services/settings.py`: `clear_reminder_channel(uow, actor)` (Manage Server; `InvalidOperation` if none is set) and `count_scheduled_server_todos(uow, guild_id)` (open server to-dos with a pending occurrence). The Manage Server message now says "change" instead of "set".
  - `/sidequest channel`: `channel` is now optional, new option `clear: bool`. Both → error; neither → "Pick a channel, or use `clear:True`". `clear:True` replies with `admin.clear_warning(...)` + `ClearChannelConfirmView` (Unset channel / Cancel, in `views/confirm.py`); the button re-checks Manage Server in the service.
  - The command payload changed, so the global sync runs once on the next start (hash differs).
  - Tests: `tests/integration/test_reminder_channel_clear.py`, `tests/unit/test_admin_clear_warning.py`.
  - Manual checks (added to the combined checklist): see "D36" items above.
- Same day, Tim: **D37**, built right away (Tim asked; uncommitted): `render.done_text` now always says "✅ Checked off **title**." (+ " Next: <timestamp>" for a repeating to-do with a next occurrence); `/todo upcoming` uses it too instead of its own text. `ShowView._done` replaces the message with only that text (no embed, no buttons) and stops the view. Tests: `tests/unit/test_render.py` (updated + one new case).
- Same day, Tim: `/todo show` → **Edit details** now refreshes the `/todo show` message on save (new details visible, confirmation as its text), instead of sending a separate reply. `DetailsModal` got an optional `on_saved` callback (ShowView passes `_refresh`); the modal then defers as a message update. `/todo details` still replies separately. `ShowView._refresh` drops the buttons if the view already timed out.

### 2026-11-12 — S7 Ops & hardening built (waiting for review)
- All checklist items done on `claude/s7-ops` (branched from `claude/s6-reminders`). Uncommitted.
- **Checks:** `ruff check .` clean · `ruff format --check .` clean · `pytest` with `TEST_DATABASE_URL`: **459 passed** (+45: health/watchdog/healthcheck, graceful shutdown, scheduler `stop()`, retention, config). Docker image not built (Tim's rule: don't verify builds). Nothing tested on the Pi or in Discord.
- **Files:** new: `src/sidequest/health.py`, `services/retention.py`, `scheduler/retention.py`, `scripts/restore-backup.sh`, `docs/claude/RUNBOOK.md`, `tests/unit/{test_health,test_client_shutdown}.py`, `tests/integration/test_retention.py`. Changed: `bot/client.py`, `scheduler/loop.py`, `cli.py`, `config.py`, `Dockerfile`, `compose.yaml`, `update.sh`, `configs/.env.example`, root `README.md`, `tests/unit/test_config.py`, `tests/integration/test_scheduler.py`, `docs/claude/{BRIEF,README}.md`.
- **What was built:**
  - `sidequest healthcheck` (exit 1 if the heartbeat is > 3 min old) + Dockerfile `HEALTHCHECK` (60 s interval, 120 s start period). It skips pydantic/discord/sqlalchemy imports so it starts fast on the Pi.
  - **D38 (Tim, mid-session: "this should be automatically restarted"):** `health.Watchdog`, a thread that `os._exit(1)`s when the heartbeat content hasn't changed for 3 min (5 min grace at start). `restart: unless-stopped` restarts the bot. Chosen over an autoheal container (needs the Docker socket).
  - Graceful shutdown: `client.serve()` installs SIGTERM/SIGINT handlers (Python as PID 1 ignores SIGTERM otherwise) and closes the client; `close()` stops the watchdog, cancels the cleanup task, lets the scheduler finish its iteration (`Scheduler.stop()`, 5 s timeout, then cancel), closes Discord and the DB engine. `compose.yaml`: `init: true` (tini) so SIGTERM also works during migrations. The heartbeat file is removed at scheduler start and written atomically.
  - History retention (D8): `HISTORY_RETENTION_DAYS` (≥ 1, unset = keep). Runs at startup and then daily.
  - `scripts/restore-backup.sh [-y] [--no-safety-dump] <file>`: validates the gzip, asks for `restore`, makes a `backups/pre-restore-*.sql.gz` safety dump, stops the bot, drops and recreates the DB, loads it with `ON_ERROR_STOP`, starts the bot (which migrates).
  - `update.sh`: confirmed it keeps 14 dumps and aborts on a failed dump. Changed: it now builds the image **before** `docker compose down`, so the bot is down only for the restart.
  - Runbook (`docs/claude/RUNBOOK.md`) and a root `README.md`.
- **Deviations:**
  - Retention also deletes old **`cancelled`** occurrences of open repeating to-dos. The segment doc lists only missed/failed/done, but each edit creates a cancelled occurrence, so without this they'd pile up forever.
  - Retention judges occurrence age by `due_at`.
- **Final review** (fresh Opus subagent): no data-loss or crash bugs; C1–C10, D1–D38, layering, `discord_time`, SQL, async blocking and "now" via `Clock` all pass. 12 hardening findings:
  - Fixed: (1) non-atomic heartbeat write could make the watchdog fire on a half-written file → temp file + `os.replace`; (2) watchdog could hang on a blocked log handler → a 5 s `os._exit` timer starts before logging; (3) Pi clock jump after boot (NTP) looked like a stale beat → watchdog uses a monotonic clock and watches for content *changes*; (4) restore couldn't run when the current DB is missing/broken → `--no-safety-dump`; (6) SIGTERM ignored during migrations → `init: true`; (7) a stop signal during command sync could start the scheduler after `close()` → `_shutting_down` flag; (8) loop docstring overstated the shutdown guarantee → reworded; (9) no client-level `allowed_mentions` safety net → `AllowedMentions.none()` on the client (reminders still pass users explicitly); (11) healthcheck imported pydantic → lazy import; (12) bot offline during the image build → build first.
  - Accepted, documented in the runbook: (5) an error that repeats every loop round (not only DB down) makes the watchdog restart the bot every ~5 min. Restarting can't fix it, but it makes the problem visible. Accepted by Tim (2026-11-12).
  - (10) to-do **details** have mentions escaped but **not** markdown, so formatting renders in embeds. Tim (2026-11-12): keep it, details show markdown → **D39**.
- **Tim, before committing:** `git add --chmod=+x scripts/restore-backup.sh` (new executable; Tim is on Windows).
- **Manual checks (Tim, on the Pi):**
  - [ ] `./update.sh` deploys; within ~2 min `docker compose ps` shows `sidequest-bot` **(healthy)**.
  - [ ] `docker compose down` logs `Received SIGTERM`, `Shutting down`, `Scheduler stopped`, `Stopped`, no traceback, and takes well under 10 s.
  - [ ] Watchdog: `docker compose pause db`, wait ~4–5 min → log shows `Reminder loop is stuck` and the bot restarts (`RestartCount` goes up); `docker compose unpause db` → healthy again.
  - [ ] Restore round trip: create a to-do, `./update.sh` (makes a backup), delete the to-do, `scripts/restore-backup.sh backups/<newest>.sql.gz` → the to-do is back and the bot is healthy.
  - [ ] Optional: `HISTORY_RETENTION_DAYS=30` in `configs/.env`, `docker compose up -d --force-recreate bot` → log shows `History cleanup on: keeping 30 days`.
- Next: none. S7 is the last segment. Open items: the combined S5+S6 checklist items blocked by DM commands (Future work), and the S1 Developer Portal checklist.
- Done: Tim committed S7 as `669478c`.

### 2026-11-12 — S8 brief written
- Tim: the personal/server list split doesn't work. Drop personal lists and DMs; a server gets several named lists with a per-user default (`/settings`), list collaborators and ownership transfer. Tim answered the open design questions in chat; the result is `segments/S8-server-lists.md` (decisions D40–D53, to be appended to BRIEF §3 by the S8 session).
- Branch `claude/s8-server-lists` was created from `claude/s7-ops` for this brief. No code changed.
- Same day, Tim confirmed the open points: `/todo move` (D48) and the default-list rule (D53) stay; `/todo upcoming` shows one list, the user's own default-list setting or else a required `list` option (D49); non-collaborator assignees get pinged but can't check off; the Default List is created on first use. Only Manage Server may rename the Default List (D51); anyone may work on its to-dos; nobody may delete it.
- Next: S8. This brief makes the DM future-work item obsolete; S8 closes it.

### 2026-11-12 — S8 Server lists built (waiting for review)
- All 8 checklist items done on `claude/s8-server-lists`. Uncommitted.
- **Checks:** `ruff check .` clean · `ruff format --check .` clean · `pytest` with `TEST_DATABASE_URL`: **570 passed** (425 unit, 145 integration; +61 list/permission service tests, +2 migration `0003` tests) · `alembic check`: no drift · the cleanup grep (S8 §6 item 6) only hits unrelated words. Nothing tested in Discord itself.
- The existing integration tests and the new ones passed on their first run against Postgres; only the migration test needed a fix (it passed ISO strings where asyncpg wants datetimes).
- **Files:** new: `migrations/versions/0003_server_lists.py`, `core/text.py` (`bold()`: markdown-escaped names in service messages), `services/lists.py`, `bot/commands/lists.py`, `bot/views/{list_delete,collaborators}.py`, `tests/integration/{test_migration_0003,test_services_lists,test_services_list_permissions}.py`. Changed: `db/models.py`, `core/{enums,errors,limits}.py`, `services/{_common,dto,permissions,todos,occurrences,subtasks,settings}.py`, `bot/{adapter,autocomplete,render,notifier,client}.py`, `bot/commands/{common,todo,repeat,todo_list,todo_view,todo_manage,settings,about}.py`, `bot/views/{listing,upcoming,show,reminder,confirm}.py`, existing tests, `docs/claude/{BRIEF,RUNBOOK,PROGRESS}.md`, `README.md`.
- **How it fits together:** `lists.ensure_guild` creates a server's settings row + ownerless "Default List" on first use (race-safe: `ON CONFLICT DO NOTHING` + `FOR UPDATE` on the settings row). `lists.resolve(uow, actor, list_id | None)` → the given list, else the user's `user_guild_settings` default, else the fallback; it's what every list-taking service calls. Permissions take the **list** (`can_work_on` + wrappers `can_add/can_edit/can_complete`, `can_rename_list`, `can_manage_list`); `_common.todo_load()` loads a to-do's list + collaborators wherever a `TodoView` is built. Open-title uniqueness: a friendly pre-check plus the `uq_todos_list_id_open_title` index mapped to `NameTaken` on flush.
- **Deviations / decisions:**
  - `ListView` has an extra `can_rename` (the rename rule differs from `can_manage` on the fallback list; `/lists show` and future UI can use it).
  - `/lists delete` → "Move them to…" only offers lists the caller **can add to** (the segment doc said "all other lists"). A list the caller can't add to would always fail with `Forbidden`; the service still checks.
  - Service error messages name lists/titles in bold with markdown escaped via `core.text.bold` (services can't import discord; the bot only escapes mentions in errors).
  - `/lists collaborators` and `/lists transfer` check fallback/permission **before** showing the select/confirmation (same rules as the service, which checks again on submit).
  - `/lists transfer` refuses a user who isn't resolved as a server `Member` ("isn't a member of this server"), and bots.
  - Reminder components now pass Manage Server from `interaction.permissions` (D50: Manage Server may check off on any list). A non-collaborator's Done/select gets the service's `Forbidden` message; the reminder stays.
  - `/todo upcoming`'s check-off select only offers to-dos the viewer may check off; with none, there's no select (the embed still lists everything).
  - `/todo list`/`upcoming` embed titles: the list name (`<name> · upcoming, next 7 days`).
  - The `list` slash option is `list_` in Python with `@app_commands.rename(list_="list")` (avoids shadowing the builtin); `CREATE_DESCRIPTIONS` uses the key `list_`.
  - `views/listing.ListView` renamed to `ListPageView` (clashed with the `ListView` DTO name).
  - `committed_sessions` fixture also truncates `todo_lists`.
  - The `/todo repeat` scope→list swap was a 4×4-line mechanical edit, done with a script instead of a Haiku agent.
- **Manual test checklist (Tim, dev bot):** the list in `segments/S8-server-lists.md` §7. Also: untick **User Install** in the Developer Portal (RUNBOOK §2).
