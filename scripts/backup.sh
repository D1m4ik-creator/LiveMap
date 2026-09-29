#!/usr/bin/env bash
set -euo pipefail

backup_dir="${1:-./backups}"
mkdir -p "$backup_dir"
umask 077
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="$backup_dir/livemap-$stamp.dump"
temporary="$target.tmp"
trap 'rm -f "$temporary"' EXIT

docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$temporary"
docker compose exec -T db pg_restore --list < "$temporary" > /dev/null
mv "$temporary" "$target"
echo "Backup saved: $target"
