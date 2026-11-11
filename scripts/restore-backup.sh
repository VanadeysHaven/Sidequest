#!/usr/bin/env bash
set -euo pipefail

# Replace the Sidequest database with a gzipped SQL backup (as made by update.sh).
# Usage: scripts/restore-backup.sh [-y|--yes] [--no-safety-dump] <backup-file>

DB_CONTAINER=sidequest-db
DB_WAIT_SECONDS=60

usage() {
  cat <<EOF
Usage: $(basename "$0") [-y|--yes] [--no-safety-dump] <backup-file>

Replace the Sidequest database with the contents of a gzipped SQL backup.
The bot is stopped during the restore and a safety dump of the current
database is made first.

Options:
  -y, --yes          Skip the confirmation prompt
  --no-safety-dump   Don't dump the current database first (use when it is missing or
                     broken, e.g. after a failed restore)
  -h, --help         Show this help and exit
EOF
}

assume_yes=false
safety_dump=true
positional=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -y|--yes)
      assume_yes=true
      shift
      ;;
    --no-safety-dump)
      safety_dump=false
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      positional+=("$@")
      break
      ;;
    -*)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      positional+=("$1")
      shift
      ;;
  esac
done

if [[ ${#positional[@]} -ne 1 ]]; then
  echo "Expected exactly one backup file argument." >&2
  usage >&2
  exit 2
fi

# Resolve the backup path before changing directory, so a relative path given by the user still works.
# readlink -m does not require the file to exist; existence is checked below.
backup_file=$(readlink -m -- "${positional[0]}")

# Run from the repo root so backups/ and compose resolve correctly.
cd "$(dirname "$(readlink -f "$0")")/.."

# Validate the backup before touching anything.
if [[ ! -f "$backup_file" || ! -r "$backup_file" ]]; then
  echo "Error: backup file not found or not readable: $backup_file" >&2
  exit 1
fi
if ! gzip -t -- "$backup_file"; then
  echo "Error: not a valid gzip file: $backup_file" >&2
  exit 1
fi

# The database container must be running; start it if it is not.
database_state=$(docker inspect --format='{{.State.Running}}' "$DB_CONTAINER" 2>/dev/null || true)
if [[ "$database_state" != "true" ]]; then
  echo "Database container not running, starting it..."
  docker compose up -d db
  waited=0
  until docker exec "$DB_CONTAINER" sh -c 'pg_isready -U "$POSTGRES_USER" -d postgres' >/dev/null 2>&1; do
    if (( waited >= DB_WAIT_SECONDS )); then
      echo "Error: database did not become ready within ${DB_WAIT_SECONDS} seconds." >&2
      exit 1
    fi
    sleep 2
    waited=$((waited + 2))
  done
fi

if [[ "$assume_yes" != true ]]; then
  echo "This will REPLACE the database in $DB_CONTAINER with the contents of:"
  echo "  $backup_file"
  echo "The bot will be stopped meanwhile."
  if [[ "$safety_dump" == true ]]; then
    echo "A safety dump of the current database is made first."
  else
    echo "NO safety dump is made (--no-safety-dump): the current database is lost."
  fi
  read -r -p "Type 'restore' to continue: " answer
  if [[ "$answer" != "restore" ]]; then
    echo "Aborted."
    exit 1
  fi
fi

# Safety dump of the current database. The pre-restore- prefix means update.sh's
# backup-* rotation never deletes it.
if [[ "$safety_dump" == true ]]; then
  echo "Making safety dump of current database..."
  mkdir -p backups
  timestamp=$(date -u +%Y%m%d-%H%M%S)
  safety_file="backups/pre-restore-$timestamp.sql.gz"
  if ! docker exec "$DB_CONTAINER" sh -c 'exec pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$safety_file.tmp"; then
    rm -f -- "$safety_file.tmp"
    echo "Error: safety dump failed. Nothing has been changed." >&2
    echo "If the current database is missing or broken, run again with --no-safety-dump." >&2
    exit 1
  fi
  mv -- "$safety_file.tmp" "$safety_file"
  echo "Safety dump saved to $PWD/$safety_file"
  retry_hint="Restore the safety dump with: $0 --no-safety-dump $PWD/$safety_file"
else
  echo "Skipping the safety dump (--no-safety-dump)."
  retry_hint="Fix the cause, then run this script again with --no-safety-dump."
fi

echo "Stopping bot..."
docker compose stop bot

echo "Recreating database..."
if ! docker exec "$DB_CONTAINER" sh -c 'exec dropdb -U "$POSTGRES_USER" --if-exists --force "$POSTGRES_DB"' \
  || ! docker exec "$DB_CONTAINER" sh -c 'exec createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" "$POSTGRES_DB"'; then
  echo "Error: could not recreate the database. The bot is left STOPPED." >&2
  echo "$retry_hint" >&2
  exit 1
fi

echo "Restoring database from $backup_file..."
if ! gunzip -c -- "$backup_file" | docker exec -i "$DB_CONTAINER" sh -c 'exec psql -v ON_ERROR_STOP=1 --quiet -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > /dev/null; then
  echo "Error: restore failed. The database may be incomplete and the bot is left STOPPED." >&2
  echo "$retry_hint" >&2
  exit 1
fi

# The bot applies database migrations on start, so an older backup is upgraded automatically.
echo "Starting bot..."
docker compose up -d bot
docker compose ps
echo "Restore complete."
