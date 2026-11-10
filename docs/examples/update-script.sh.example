#!/usr/bin/env bash
echo "Setting up..."
mkdir backups -p
mkdir configs -p

echo "Pulling latest version from Git..."
git fetch
git pull

commit=$(git log --pretty=format:'%h' -n 1)
branch=$(git branch --show-current)
time_file=$(date +%Y%m%d%H%M%S)
time_bot=$(date "+%d-%m-%Y %H:%M:%S \(UTC\)")

echo "Deploying $branch > $commit"
echo "Updating configs..."
rm configs/git.env -f
touch configs/git.env
{
  echo "COMMIT=$commit
  BRANCH=$branch
  DEPLOY_TIME=$time_bot"
} >> configs/git.env

database_state=$(docker inspect --format="{{.State.Running}}" aurorahue-db 2>/dev/null)
if [[ $* == "--skip-db" ]];
then
  echo "Skipping backup database"
else
  if [ "$database_state" == "true" ];
  then
    echo "Backing up database..."
    docker exec -t aurorahue-db sh -c 'exec pg_dump -U "${POSTGRES_USER}" "${POSTGRES_DB}"' > backups/backup-"$time_file".sql
  fi
fi

echo "Shutting down bot..."
docker compose down

echo "Rebuilding images and launching..."
docker compose up -d --remove-orphans --build

echo "Done! Bot will connect to Discord shortly."
