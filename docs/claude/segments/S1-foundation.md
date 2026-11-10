# S1 — Foundation

**Goal:** a deployable skeleton. `docker compose up` starts Postgres and a bot that connects with no intents and answers `/sidequest about`. Tim deploys it to the Pi with `update.sh` to catch arm64 problems early.

**Depends on:** nothing. **Branch:** `claude/s1-foundation`.

## Checklist

### 1. Repo hygiene — Haiku
- `.gitattributes`: `* text=auto eol=lf`; `*.sh text eol=lf`; binary types marked binary. (Tim's working copy currently shows `README.md` modified only by line endings — this fixes that class of problem.)
- `.gitignore`: `.env`, `configs/*` (except `!configs/.env.example`, D33), `backups/`, `.venv/`, `__pycache__/`, `*.egg-info/`, `.pytest_cache/`, `.ruff_cache/`, `dist/`, `build/`.
- `.dockerignore`: same plus `.git/`, `docs/`, `tests/`, `backups/`, `configs/`.

### 2. Packaging — main session
- `pyproject.toml` (hatchling, src layout):
  - `name = "sidequest"`, `requires-python = ">=3.12,<3.13"` (D31), version `0.1.0`.
  - deps: `discord.py>=2.7,<3`, `sqlalchemy[asyncio]>=2.0,<3`, `asyncpg`, `alembic`, `pydantic-settings>=2`, `tzdata`.
  - `[project.optional-dependencies] dev`: `pytest`, `pytest-asyncio`, `ruff`, `pip-tools`.
  - `[project.scripts] sidequest = "sidequest.cli:main"`.
  - `[tool.ruff]` line-length 100, sensible rule set (E, F, I, UP, B, ASYNC, SIM). `[tool.pytest.ini_options]` asyncio_mode auto, testpaths.
- `scripts/compile-requirements.sh` — runs pip-compile **inside** `python:3.12-slim` via `docker run` (so output matches the Linux image, not Tim's Windows machine):
  - `pip-compile --strip-extras -o requirements.txt pyproject.toml`
  - `pip-compile --extra dev --strip-extras -o requirements-dev.txt pyproject.toml`
- Generate both requirements files with the script.

### 3. Config & CLI — main session
- `config.py` (pydantic-settings, reads env + `configs/.env`; D33):
  `DISCORD_TOKEN` (secret), `DATABASE_URL` (`postgresql+asyncpg://…`), `DEFAULT_TIMEZONE="UTC"` (validated as IANA; D25), `LOG_LEVEL="INFO"`, `SYNC_GLOBAL: bool = True`, `SYNC_GUILD_IDS: list[int]` (comma-separated; D32), `RUN_MIGRATIONS=True`, `COMMIT`, `BRANCH`, `DEPLOY_TIME: int | None` (unix seconds, from `configs/git.env`).
- `logging.py`: stdout logging, level from config, discord.py logger at WARNING unless DEBUG.
- `cli.py` (argparse):
  - `sidequest` (no args) → run migrations if `RUN_MIGRATIONS`, then start the bot.
  - `sidequest migrate` → `alembic upgrade head` only.
  - Reserve `web` (prints "not implemented yet", exit 2).
- `__main__.py` → `cli.main()`.

### 4. Bot skeleton — main session
- `bot/client.py`: subclass `discord.Client` with `app_commands.CommandTree`, `intents=discord.Intents.none()`.
  - `setup_hook`: register command groups; `SYNC_GLOBAL=true` → global sync, then sync each `SYNC_GUILD_IDS` guild with no commands (deletes stale guild copies); `false` → copy global → each listed guild, clear + sync global (empty), sync each guild (D32). A failing guild sync logs a warning and does not stop startup. (Hash-based sync skipping comes in S5.)
  - App supports guild and user installs; set `allowed_installs`/`allowed_contexts` per command (see S5 for the full matrix).
- `/sidequest about` (guild + user install, all contexts): version, commit, branch, deploy time as a Discord timestamp (`<t:DEPLOY_TIME:F>`), uptime as `<t:start:R>`.
  - Put a minimal `core/discord_time.py` with `ts(dt, style)` here; S3 completes it.

### 5. Database plumbing — main session
- `db/session.py`: async engine + `async_sessionmaker` from `DATABASE_URL`; `db/base.py`: `DeclarativeBase` with naming conventions for constraints.
- Alembic in `migrations/` using the async template, URL from `config`. An empty initial revision is fine; S2 adds tables.

### 6. Docker — Haiku (from this spec), reviewed
- `Dockerfile`: `python:3.12-slim`; non-root user; `ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1`; `COPY requirements.txt` → `pip install --no-cache-dir -r requirements.txt`; copy `pyproject.toml`, `src/`, `migrations/`, `alembic.ini` → `pip install --no-deps --no-cache-dir .`; `CMD ["sidequest"]`.
- `compose.yaml`:
  - `db`: `postgres:17-alpine`, `container_name: sidequest-db`, env `POSTGRES_USER/PASSWORD/DB` via `env_file: configs/.env` (D33), named volume `sidequest-db-data`, healthcheck `pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB`, `restart: unless-stopped`.
  - `bot`: `build: .`, `container_name: sidequest-bot`, `env_file: [configs/.env, {path: configs/git.env, required: false}]` (D33), `depends_on: db: condition: service_healthy`, `restart: unless-stopped`, logging `json-file` with `max-size: 10m`, `max-file: "3"` (SD card).
- `compose.test.yaml`: a throwaway `db-test` Postgres on port 55432 with tmpfs storage, for integration tests.
- `configs/.env.example` with every variable and comments (D33).

### 7. Update script — Haiku (port of `docs/examples/update-script.sh.example`), reviewed
Write `update.sh` at repo root. Keep the example's flow, but:
- `set -euo pipefail`; `cd` to the script's own directory first.
- `git pull --ff-only` (abort on divergence, don't create merge commits on the server).
- Container name `sidequest-db`.
- Proper flag parsing (`--skip-db`, `--help`) instead of `[[ $* == "--skip-db" ]]`.
- `configs/git.env`: `COMMIT`, `BRANCH`, and `DEPLOY_TIME=$(date -u +%s)` (unix seconds so the bot can render it as a Discord timestamp; this also fixes the example's stray `\(UTC\)` backslashes and non-UTC `date`).
- Backup: `pg_dump` via `docker exec` **without `-t`** (a TTY corrupts dumps with `\r`), gzip it, abort the update if the dump fails, keep the newest 14 backups.
- End with `docker compose ps`.
- Tell Tim to run `git add --chmod=+x update.sh`.

### 8. Tests — Haiku
- `tests/unit/test_config.py` (defaults, invalid timezone rejected).
- `tests/unit/test_cli.py` (argument routing with the bot start mocked).
- `tests/unit/test_layering.py` (BRIEF §5.2 import rules; passes trivially now, guards later segments).

## Acceptance
- `ruff` clean, unit tests pass.
- `docker compose up --build` locally: db healthy, bot logs in, `/sidequest about` answers in a guild listed in `SYNC_GUILD_IDS`.
- Manual (Tim): run `update.sh` on the Pi; bot comes online; backup file appears on the second run.

## Out of scope
Tables (S2), real commands (S5), scheduler (S6).
