FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN pip install uv==0.12.5 && uv sync --frozen --no-dev && \
    useradd --system --home /app --shell /usr/sbin/nologin livemap
COPY alembic.ini ./
COPY alembic ./alembic
COPY demo ./demo
USER livemap
EXPOSE 8000
CMD ["uvicorn", "livemap.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
