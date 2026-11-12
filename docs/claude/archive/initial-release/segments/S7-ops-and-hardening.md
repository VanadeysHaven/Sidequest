# S7 — Ops & hardening

**Goal:** the bot is pleasant to run on the Pi for months: health-checked, backed up, documented, reviewed.

**Depends on:** S1–S6. **Branch:** `claude/s7-ops`.

## Checklist

### 1. Health & shutdown — main session
- Docker `HEALTHCHECK` for `bot`: a small `sidequest healthcheck` CLI subcommand that exits non-zero if the scheduler heartbeat file (S6) is older than 3 minutes.
- Graceful SIGTERM: stop the scheduler loop after the current iteration, close the Discord client and DB engine. `docker compose down` should not log tracebacks.

### 2. History retention (D8) — Haiku, reviewed
- Optional env `HISTORY_RETENTION_DAYS` (unset = keep forever). When set, a daily task deletes to-dos with status `done`/`cancelled` and `completed_at` (or `updated_at`) older than N days, plus `missed`/`failed`/`done` occurrences of open recurring to-dos older than N days.

### 3. Backups — Haiku, reviewed
- Confirm `update.sh` keeps 14 gzipped dumps and aborts on dump failure (S1).
- Add `scripts/restore-backup.sh <file>`: stops `bot`, restores into `sidequest-db` (drop & recreate DB, `gunzip | psql`), starts `bot`. Asks for confirmation.

### 4. Pi notes (go into the runbook)
- 64-bit Raspberry Pi OS; Docker Engine + Compose plugin.
- Prefer Docker's data root on an SSD over the SD card if available (Postgres writes); compose already caps log size.
- Postgres 17 defaults are fine for this workload; major-version upgrades need dump/restore (document the steps).

### 5. Documentation — **Opus 5.5 only**
- `docs/claude/RUNBOOK.md`: first-time Pi setup, Discord Developer Portal setup (install contexts, scopes, permissions, no privileged intents), `.env` reference, deploying with `update.sh`, restore, viewing logs, rotating the token, upgrading Postgres.
- Root `README.md`: short human intro, feature list, link to the runbook.
- Final `PROGRESS.md` update.

### 6. Final review — fresh Opus subagent (not the session that wrote the code)
Give it `BRIEF.md` §2–§5 and the repo; ask it to check: every constraint C1–C10 and decision D1–D16 is honoured; layering rules; no point in time printed without `core.discord_time`; no `allowed_mentions` gaps; no SQL injection or unescaped user text; no blocking calls in async code. It reports findings; the main session fixes them; Opus records the outcome in `PROGRESS.md`.

## Acceptance
Healthcheck turns healthy on the Pi; `update.sh` deploy + `restore-backup.sh` round-trip tested by Tim; review findings resolved or explicitly deferred with Tim's OK.
