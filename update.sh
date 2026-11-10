#!/usr/bin/env bash
set -euo pipefail

# Run from the script's own directory so backups/, configs/ and compose resolve correctly.
cd "$(dirname "$(readlink -f "$0")")"

DB_CONTAINER=sidequest-db
KEEP_BACKUPS=14

usage() {
  cat <<EOF
Usage: $(basename "$0") [--skip-db] [-h|--help]

Pull the latest Sidequest code, back up the database, and redeploy with Docker Compose.

Options:
  --skip-db    Skip the database backup
  -h, --help   Show this help and exit
EOF
}

skip_db=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-db)
      skip_db=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

echo "Setting up..."
mkdir -p backups configs

echo "Pulling latest version from Git..."
git fetch
if ! git pull --ff-only; then
  echo "git pull --ff-only failed (the branch may have diverged from its upstream). Aborting update." >&2
  exit 1
fi

commit=$(git rev-parse --short HEAD)
branch=$(git branch --show-current)
deploy_time=$(date -u +%s)

echo "Deploying $branch > $commit"
echo "Updating configs..."
printf 'COMMIT=%s\nBRANCH=%s\nDEPLOY_TIME=%s\n' "$commit" "$branch" "$deploy_time" > configs/git.env

if [[ "$skip_db" == true ]]; then
  echo "Skipping database backup"
else
  database_state=$(docker inspect --format='{{.State.Running}}' "$DB_CONTAINER" 2>/dev/null || true)
  if [[ "$database_state" == "true" ]]; then
    echo "Backing up database..."
    timestamp=$(date -u +%Y%m%d-%H%M%S)
    backup_file="backups/backup-$timestamp.sql.gz"
    if ! docker exec "$DB_CONTAINER" sh -c 'exec pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$backup_file.tmp"; then
      rm -f -- "$backup_file.tmp"
      echo "Error: database backup failed. Aborting update before touching the running containers." >&2
      exit 1
    fi
    mv -- "$backup_file.tmp" "$backup_file"
    echo "Backup saved to $backup_file"

    # Keep only the newest $KEEP_BACKUPS backups. "|| true" covers the no-matches case,
    # where ls fails and pipefail would otherwise abort the script.
    ls -1t backups/backup-*.sql.gz 2>/dev/null | tail -n +"$((KEEP_BACKUPS + 1))" | xargs -r rm -- || true
  else
    echo "Database container not running, skipping backup"
  fi
fi

echo "Shutting down bot..."
docker compose down

echo "Rebuilding images and launching..."
docker compose up -d --remove-orphans --build

echo "Done! Bot will connect to Discord shortly."
docker compose ps
