import asyncio
from pathlib import Path

import httpx
from pydantic import SecretStr
from sqlalchemy.orm import configure_mappers
from sqlalchemy.ext.asyncio import create_async_engine

from livemap.api.app import app
from livemap.api.routers import health
from livemap.core.config import ROOT_DIR, Config, DatabaseConfig
from livemap.db.base import Base
from livemap.db.models import Camera, Object


def request(path: str) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.get(path)

    return asyncio.run(send())


def test_settings_load_root_env_and_async_driver() -> None:
    assert ROOT_DIR == Path(__file__).resolve().parents[1]
    settings = Config(_env_file=ROOT_DIR / ".env.example")
    assert settings.postgres_user == "livemap"

    url = DatabaseConfig(
        user="user@example",
        password=SecretStr("p@ss word"),
        db="livemap",
        host="localhost",
        port=5432,
    ).get_db_url()
    assert url.username == "user@example"
    assert url.password == "p@ss word"
    assert "p@ss word" not in str(url)

    engine = create_async_engine(url)
    try:
        assert engine.dialect.driver == "asyncpg"
    finally:
        asyncio.run(engine.dispose())


def test_models_are_registered_once_with_relationships() -> None:
    configure_mappers()
    assert set(Base.metadata.tables) == {"objects", "cameras"}
    assert Camera.__table__.c.object_id.foreign_keys
    assert Object.cameras.property.back_populates == "object"


def test_liveness_and_error_format() -> None:
    response = request("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    response = request("/api/v1/missing")
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Resource not found"}
    }


def test_readiness_reports_database_state(monkeypatch) -> None:
    async def ready() -> None:
        return None

    async def unavailable() -> None:
        raise ConnectionError("test database is offline")

    monkeypatch.setattr(health, "check_database", ready)
    response = request("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    monkeypatch.setattr(health, "check_database", unavailable)
    response = request("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "database_unavailable",
            "message": "Database is unavailable",
        }
    }
