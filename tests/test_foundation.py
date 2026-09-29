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
from livemap.db.models import Camera, Place


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
    assert set(Base.metadata.tables) == {
        "places", "sources", "cameras", "camera_checks", "camera_reports",
        "admin_users", "admin_sessions", "audit_events"
    }
    assert Camera.__table__.c.place_id.foreign_keys
    assert Place.cameras.property.back_populates == "place"


def test_liveness_and_error_format() -> None:
    response = request("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    response = request("/api/v1/missing")
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Resource not found"}
    }


def test_request_observability_does_not_log_query_secrets(caplog) -> None:
    with caplog.at_level("INFO", logger="livemap.requests"):
        response = request("/api/v1/health/live?token=DO_NOT_LOG_THIS")
    assert response.headers["x-request-id"]
    assert '"route": "/health/live"' in caplog.text
    assert "DO_NOT_LOG_THIS" not in caplog.text
    metrics = request("/internal/metrics")
    assert metrics.status_code == 200
    assert "livemap_http_requests_total" in metrics.text


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


def test_openapi_exposes_one_versioned_contract() -> None:
    paths = app.openapi()["paths"]
    assert {
        "/api/v1/places",
        "/api/v1/places/search",
        "/api/v1/places/{place_id}",
        "/api/v1/admin/login",
        "/api/v1/admin/places",
        "/api/v1/admin/cameras",
        "/api/v1/admin/sources",
        "/api/v1/admin/import/preview",
        "/api/v1/admin/import/apply",
    } <= set(paths)
    assert paths["/api/v1/places"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert paths["/api/v1/admin/places"]["post"]["requestBody"]
