# Sidequest — runbook

> Written by Claude (Opus 5.5), 2026-11-12. How to set up, run, back up and repair Sidequest
> on the Raspberry Pi. Commands run in the repo directory on the Pi unless noted.

## Contents

1. [First-time Pi setup](#1-first-time-pi-setup)
2. [Discord Developer Portal](#2-discord-developer-portal)
3. [Configuration (`configs/.env`)](#3-configuration-configsenv)
4. [Deploying and updating](#4-deploying-and-updating)
5. [Health and automatic restarts](#5-health-and-automatic-restarts)
6. [Logs](#6-logs)
7. [Backups and restore](#7-backups-and-restore)
8. [History retention](#8-history-retention)
9. [Rotating the bot token](#9-rotating-the-bot-token)
10. [Upgrading PostgreSQL](#10-upgrading-postgresql)
11. [Dev bot](#11-dev-bot)

---

## 1. First-time Pi setup

Requirements: 64-bit Raspberry Pi OS (`uname -m` prints `aarch64`, D30), Docker Engine with
the Compose plugin, git.

1. Install Docker and let your user run it (log out and back in afterwards):
   ```sh
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker "$USER"
   ```
2. Optional, recommended: keep Docker's data on an SSD instead of the SD card. Postgres writes
   often, and SD cards wear out. See [SSD data root](#ssd-data-root) below.
3. Clone the repo and create the config:
   ```sh
   git clone <repo-url> sidequest && cd sidequest
   cp configs/.env.example configs/.env
   chmod 600 configs/.env
   nano configs/.env        # fill in, see §3
   ```
4. Make sure the scripts are executable (`ls -l update.sh scripts/`). If not:
   `chmod +x update.sh scripts/*.sh`. The lasting fix is on the Windows side:
   `git add --chmod=+x <file>` and commit.
5. Start it: `./update.sh` (the first run skips the backup because no database runs yet).
6. Check: `docker compose ps` shows `sidequest-db` healthy and `sidequest-bot` **healthy**
   within about 2 minutes (§5). `docker compose logs bot` should show `Logged in as …`.
7. Invite the bot to your server (§2), then run `/sidequest channel` there to pick the
   reminder channel.

### SSD data root

With the SSD mounted at e.g. `/mnt/ssd`:

```sh
sudo systemctl stop docker docker.socket
sudo rsync -aP /var/lib/docker/ /mnt/ssd/docker/
echo '{ "data-root": "/mnt/ssd/docker" }' | sudo tee /etc/docker/daemon.json
sudo systemctl start docker
docker info --format '{{.DockerRootDir}}'   # should print /mnt/ssd/docker
```

If `/etc/docker/daemon.json` already exists, add the `data-root` key to it instead of
overwriting it. Once everything runs, `/var/lib/docker` can be removed to free the SD card.

Container logs are already capped (10 MB × 3 files per container, `compose.yaml`).

---

## 2. Discord Developer Portal

Use a separate application for production and for development (§11).

1. <https://discord.com/developers/applications> → **New Application**.
2. **Bot** tab: **Reset Token** and copy it into `DISCORD_TOKEN` (shown once). Leave all
   three **Privileged Gateway Intents** off; the bot connects with no intents at all (D11).
3. **Installation** tab:
   - Installation contexts: tick **Guild Install** and **User Install**.
   - Guild Install scopes: `applications.commands`, `bot`.
     Permissions: **View Channels**, **Send Messages**, **Embed Links**.
   - User Install scopes: `applications.commands`.
   - Install link: **Discord Provided Link**. Open it to add the bot to a server.
4. In each server, the reminder channel must allow the bot to view it, send messages and
   embed links. `/sidequest channel` checks this by posting a short message there.

Notes:
- Personal reminders arrive as DMs. Discord only lets a bot DM someone who shares a server
  with it and allows DMs from server members. A refused DM is recorded and the user is told
  on their next command (D26).
- Commands are registered on startup (D32). Global command changes can take up to an hour
  to show in every client; restarting Discord (Ctrl+R) usually speeds it up.

---

## 3. Configuration (`configs/.env`)

`configs/` is git-ignored; `configs/.env.example` is the template. Both compose services read
`configs/.env` (D33). Empty values count as unset.

| Variable | Default | Meaning |
|---|---|---|
| `DISCORD_TOKEN` | — (required) | Bot token (§2). Secret. |
| `POSTGRES_USER` | — | Database user, created by the `db` container on first start. |
| `POSTGRES_PASSWORD` | — | Its password. Change from `change-me`. |
| `POSTGRES_DB` | — | Database name. |
| `DATABASE_URL` | — (required) | `postgresql+asyncpg://USER:PASSWORD@db:5432/DB`, matching the three above. Host `db` is the compose service. |
| `DEFAULT_TIMEZONE` | `UTC` | IANA name (e.g. `Europe/Amsterdam`) for users who never ran `/settings timezone` (D25). |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`. |
| `SYNC_GLOBAL` | `true` | `true`: commands everywhere (production). `false`: only in `SYNC_GUILD_IDS` (dev bot, §11). |
| `SYNC_GUILD_IDS` | empty | Comma-separated server IDs. With `SYNC_GLOBAL=true` these servers get leftover server-only commands removed. |
| `RUN_MIGRATIONS` | `true` | Apply database migrations on start. |
| `HISTORY_RETENTION_DAYS` | empty | Delete history older than this many days (§8). Empty: keep forever. |

`update.sh` writes `configs/git.env` (`COMMIT`, `BRANCH`, `DEPLOY_TIME`), which `/sidequest
about` shows. Don't set those yourself.

The `POSTGRES_*` values only take effect when the database volume is created. To change the
password later, change it inside Postgres too:
`docker exec -it sidequest-db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'` →
`ALTER USER sidequest PASSWORD '…';`, then update `.env` and recreate the bot (§9, step 3).

---

## 4. Deploying and updating

```sh
./update.sh            # pull, back up the database, rebuild, restart
./update.sh --skip-db  # same without the backup
```

What it does:
1. `git pull --ff-only` (aborts if the branch has diverged).
2. Writes `configs/git.env`.
3. If `sidequest-db` runs: `pg_dump` → `backups/backup-<UTC time>.sql.gz`. A failed dump
   aborts the update before anything is stopped. Only the newest **14** backups are kept.
4. `docker compose build` while the old bot keeps running (a failed build aborts here, with
   the old bot still up), then `docker compose down` and `docker compose up -d --remove-orphans`.

The bot applies database migrations on start (`RUN_MIGRATIONS=true`), then logs in and
syncs commands. Run `docker compose ps` a few minutes later: the bot should be **healthy**.

`docker compose down` stops the bot gracefully: it finishes the reminder it is posting
(at most 5 s), closes the Discord connection and the database pool, and logs `Stopped`.

---

## 5. Health and automatic restarts

The reminder loop writes a heartbeat file (`/tmp/sidequest-heartbeat` in the container)
after every successful round, at least once a minute. A round fails when, for example, the
database can't be reached.

- **Docker healthcheck:** `sidequest healthcheck` runs every 60 s and fails when the
  heartbeat is older than 3 minutes. `docker compose ps` shows `healthy` / `unhealthy`
  (`starting` for the first 2 minutes). Details:
  `docker inspect --format '{{json .State.Health}}' sidequest-bot`.
- **Automatic restart (D38):** Docker only *marks* a container unhealthy. A watchdog thread
  inside the bot exits the process when the heartbeat hasn't changed for 3 minutes (or is
  still missing 5 minutes after start), and `restart: unless-stopped` starts it again. The
  log then shows `Reminder loop is stuck (…); exiting so Docker restarts the bot`. The
  watchdog measures time on a monotonic clock, so the Pi's clock jumping forward after boot
  (NTP sync) doesn't trigger it.
- Restart count: `docker inspect --format '{{.RestartCount}}' sidequest-bot`.

A bot that keeps restarting every ~5 minutes means every loop round fails. Usually the
database is down or unreachable: check `docker compose ps db` and `docker compose logs db`.
If the database is fine, the log line `Scheduler iteration failed` before each restart has
the traceback; restarting won't fix that kind of error, so it needs a code fix. This restart
loop is accepted (final review, S7): it makes the problem visible instead of silently
sending no reminders.

Run the check by hand: `docker exec sidequest-bot sidequest healthcheck`.

---

## 6. Logs

```sh
docker compose logs -f bot              # follow
docker compose logs --since 1h bot      # last hour
docker compose logs db                  # database
```

Raise the detail level with `LOG_LEVEL=DEBUG` in `configs/.env`, then
`docker compose up -d --force-recreate bot`. Set it back afterwards; DEBUG is chatty.

Things worth knowing in the log:
- `Reminder N could not be posted: forbidden / channel_gone / no_channel / dm_closed` — a
  reminder failed; the reason says why (missing permission, deleted channel, no reminder
  channel set, DMs closed).
- `Scheduler iteration failed` — usually the database; the loop retries every 60 s.

---

## 7. Backups and restore

Backups are made by every `./update.sh` run (§4). Make one by hand:

```sh
docker exec sidequest-db sh -c 'exec pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  | gzip > "backups/manual-$(date -u +%Y%m%d-%H%M%S).sql.gz"
```

Copy backups off the Pi now and then (they live in `backups/` next to the repo, on the same
disk as the database).

### Restore

```sh
scripts/restore-backup.sh backups/backup-20261112-080000.sql.gz
```

The script:
1. Checks that the file is a valid gzip file, and starts the `db` container if needed.
2. Asks you to type `restore` (skip with `--yes`).
3. Saves the current database to `backups/pre-restore-<UTC time>.sql.gz` first. `update.sh`
   never deletes these; remove them yourself when no longer needed.
4. Stops the bot, drops and recreates the database, loads the backup.
5. Starts the bot, which migrates an older backup to the current schema.

If loading fails, the bot stays stopped and the database may be incomplete. The script prints
what to run next: fix the cause and run it again, or restore the `pre-restore-…` dump it just
made. Use `--no-safety-dump` when the current database is missing or broken (the safety dump
would fail then), e.g. when retrying after a failed restore.

---

## 8. History retention

Finished to-dos are kept as history (D8). With `HISTORY_RETENTION_DAYS=N` set, the bot
deletes, once at startup and then once a day:
- to-dos that are done or deleted, finished more than N days ago (with their subtasks and
  reminder records);
- reminder records (done, missed, failed, cancelled) more than N days old of repeating
  to-dos that are still open.

Open to-dos and their upcoming reminders are never touched. The log reports what was
deleted (`History cleanup: deleted …`). Deleted history is only recoverable from a backup.

---

## 9. Rotating the bot token

Do this if the token leaked, or regularly if you like.

1. Developer Portal → your application → **Bot** → **Reset Token**. The old token stops
   working right away, so the bot disconnects.
2. Put the new token in `DISCORD_TOKEN` in `configs/.env`.
3. `docker compose up -d --force-recreate bot` (a plain `restart` does not reread `.env`).
4. `docker compose logs -f bot` → `Logged in as …`.

---

## 10. Upgrading PostgreSQL

Minor updates (17.x → 17.y) need nothing special: `docker compose pull db` and
`docker compose up -d db`, or let a rebuild pick them up.

A **major** upgrade (e.g. 17 → 18) can't reuse the data directory. Dump, start fresh, restore:

1. Back up:
   ```sh
   docker exec sidequest-db sh -c 'exec pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
     | gzip > backups/pre-upgrade.sql.gz
   gzip -t backups/pre-upgrade.sql.gz && ls -lh backups/pre-upgrade.sql.gz
   ```
2. Stop everything: `docker compose down`.
3. Find and remove the old data volume (the dump from step 1 is now your only copy):
   ```sh
   docker volume ls | grep sidequest-db-data
   docker volume rm <name>          # e.g. sidequest_sidequest-db-data
   ```
4. In `compose.yaml`, change `image: postgres:17-alpine` to the new version. Read that
   version's image notes first: newer images may expect the volume at a different path
   (e.g. `/var/lib/postgresql` instead of `/var/lib/postgresql/data`); adjust the mount.
5. Start the new database: `docker compose up -d db`, wait for `healthy` in
   `docker compose ps`.
6. Restore: `scripts/restore-backup.sh backups/pre-upgrade.sql.gz` (it also starts the bot).
7. Check `docker compose ps` and try `/todo list`. Commit the `compose.yaml` change, and
   update D10 in `docs/claude/BRIEF.md`.

---

## 11. Dev bot

A second Discord application for testing, so command changes don't reach real servers.

- In its `configs/.env`: `SYNC_GLOBAL=false` and `SYNC_GUILD_IDS=<test server id>`. Commands
  then appear in that server instantly, and the dev bot has **no** commands in DMs (D32).
- It needs its own database (another checkout with its own compose project, or run it
  locally against a local Postgres). Never point two bots at one database: both schedulers
  would post the same reminders.

Local checks on the dev machine (Windows, `.venv`):

```sh
ruff check . && ruff format --check .
docker compose -f compose.test.yaml up -d
TEST_DATABASE_URL=postgresql+asyncpg://sidequest:sidequest@localhost:55432/sidequest_test pytest
```
