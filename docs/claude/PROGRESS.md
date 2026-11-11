# Progress

> Updated by Claude (Opus 5.5) at the end of every session.

## Status

| Seg | Title | Status | Branch |
|---|---|---|---|
| S1 | Foundation | ✅ done | `claude/s1-foundation` |
| S2 | Data model | ✅ done | `claude/s2-data-model` |
| S3 | Time & recurrence | 👀 review | `claude/s3-time-and-recurrence` |
| S4 | Services | ⏭️ next | — |
| S5 | Commands | ⬜ todo | — |
| S6 | Reminders | ⬜ todo | — |
| S7 | Ops & hardening | ⬜ todo | — |

Legend: ⬜ todo · ⏭️ next · 🔨 in progress · 👀 waiting for Tim's review/commit · ✅ done

## Before S1 (Tim)
- [x] Review assumptions A1–A14 (done 2026-11-10 → decisions D17–D29).
- [x] A9: Pi confirmed 64-bit (`aarch64` / `arm64`) → D30.
- [ ] Create a **dev** Discord application (separate from production) with a test server; note its token and the test server ID for `SYNC_GUILD_IDS`.
- [ ] In the Developer Portal → Installation: enable **Guild Install** (scopes `applications.commands`, `bot`; permissions View Channel, Send Messages, Embed Links) and **User Install** (`applications.commands`). Leave all privileged intents off.

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
- Next: S4 Services.

