#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ! -f "$1" ]]; then
  echo "Usage: scripts/verify-backup.sh backups/livemap-TIMESTAMP.dump" >&2
  exit 2
fi

backup="$1"
temporary_db="livemap_restore_$(date -u +%s)_$$"
created=0
cleanup() {
  if [[ "$created" == 1 ]]; then
    docker compose exec -T db sh -c 'dropdb -U "$POSTGRES_USER" --if-exists "$1"' sh "$temporary_db"
  fi
}
trap cleanup EXIT

docker compose exec -T db sh -c 'createdb -U "$POSTGRES_USER" "$1"' sh "$temporary_db"
created=1
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$1" --no-owner --exit-on-error' sh "$temporary_db" < "$backup"
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$1" -Atc "SELECT count(*) FROM places"' sh "$temporary_db"
echo "Restore verified in isolated database: $temporary_db"
