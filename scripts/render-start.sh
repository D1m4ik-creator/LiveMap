#!/bin/sh
set -eu

export PATH="$(pwd)/.venv/bin:$PATH"
export PUBLIC_ORIGIN="${PUBLIC_ORIGIN:-${RENDER_EXTERNAL_URL:-http://localhost:10000}}"
alembic upgrade head
unset POSTGRES_MIGRATION_USER POSTGRES_MIGRATION_PASSWORD
exec uvicorn livemap.api.app:app --host 0.0.0.0 --port "${PORT:-10000}" --no-access-log
