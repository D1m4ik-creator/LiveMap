#!/bin/sh
set -eu

export PUBLIC_ORIGIN="${PUBLIC_ORIGIN:-${RENDER_EXTERNAL_URL:-http://localhost:10000}}"
alembic upgrade head
exec uvicorn livemap.api.app:app --host 0.0.0.0 --port "${PORT:-10000}" --no-access-log
