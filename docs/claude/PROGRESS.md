# Progress

> Updated by Claude (Opus 5.5) at the end of every session.

## Status

| Seg | Title | Status | Branch |
|---|---|---|---|
| S1 | Foundation | ✅ done | `claude/s1-foundation` |
| S2 | Data model | 👀 waiting for Tim's review/commit | `claude/s2-data-model` |
| S3 | Time & recurrence | ⏭️ next | — |
| S4 | Services | ⬜ todo | — |
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

### 2026-11-10 — S2 Data model built (waiting for review)
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
- Next: S3 Time & recurrence.
