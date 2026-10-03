import asyncio
import os
import subprocess
import sys
import time
import statistics
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from livemap.api.app import app
from livemap.core.config import ROOT_DIR, get_settings
from livemap.core.engine import get_session
from livemap.db.models import AdminUser, Camera, CameraCheck, Place, Source
from livemap.services.auth import hash_password
from livemap.services.catalog_admin import point
from livemap.services.camera_probe import ProbeResult
from livemap.worker import DueCamera, run_once, save_check


@pytest.fixture(scope="module")
def test_database_url():
    name = f"livemap_test_{uuid4().hex[:12]}"
    admin_url = get_settings().database.get_db_url().set(database="postgres")

    async def create_database() -> None:
        engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as connection:
                await connection.execute(text(f'CREATE DATABASE "{name}"'))
        finally:
            await engine.dispose()

    asyncio.run(create_database())
    env = {**os.environ, "POSTGRES_DB": name}
    try:
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT_DIR, env=env, check=True)
        subprocess.run([sys.executable, "-m", "alembic", "downgrade", "base"], cwd=ROOT_DIR, env=env, check=True)
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT_DIR, env=env, check=True)
        yield get_settings().database.get_db_url().set(database=name)
    finally:
        async def drop_database() -> None:
            engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
            try:
                async with engine.connect() as connection:
                    await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            finally:
                await engine.dispose()

        asyncio.run(drop_database())


def test_admin_catalog_map_search_and_import(test_database_url, monkeypatch) -> None:
    async def run() -> None:
        engine = create_async_engine(test_database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def test_session():
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = test_session
        try:
            async with engine.connect() as connection:
                assert (await connection.execute(text("SELECT postgis_version()"))).scalar_one()
                index = (await connection.execute(text(
                    "SELECT indexdef FROM pg_indexes WHERE tablename='places' AND indexname='ix_places_geometry'"
                ))).scalar_one()
                assert "using gist" in index.lower()
            async with factory() as session:
                session.add(AdminUser(username="root", password_hash=hash_password("test-password-123"), role="admin"))
                await session.commit()

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                async def call(method: str, path: str, *, token: str | None = None, **kwargs):
                    headers = {"Authorization": f"Bearer {token}"} if token else {}
                    return await client.request(method, path, headers=headers, **kwargs)

                assert (await call("GET", "/api/v1/admin/places")).status_code == 401
                login = await call("POST", "/api/v1/admin/login", json={"username": "root", "password": "test-password-123"})
                assert login.status_code == 200, login.text
                token = login.json()["access_token"]

                editor = await call("POST", "/api/v1/admin/users", token=token, json={
                    "username": "editor", "password": "editor-password-123", "role": "editor"
                })
                assert editor.status_code == 201, editor.text
                editor_login = await call("POST", "/api/v1/admin/login", json={"username": "editor", "password": "editor-password-123"})
                editor_token = editor_login.json()["access_token"]

                place = await call("POST", "/api/v1/admin/places", token=editor_token, json={
                    "slug": "moscow-square", "name": "Красная площадь", "address": "Красная площадь",
                    "city": "Москва", "region": "Москва", "category": "square",
                    "coordinates": [37.6208, 55.7539],
                })
                assert place.status_code == 201, place.text
                place_id = place.json()["id"]
                assert (await call("GET", f"/api/v1/admin/places/{place_id}", token=editor_token)).status_code == 200
                assert (await call("GET", "/api/v1/admin/places", token=editor_token)).status_code == 200
                assert (await call("PATCH", f"/api/v1/admin/places/{place_id}", token=editor_token, json={"address": "Новый адрес"})).status_code == 200
                assert (await call("POST", "/api/v1/admin/places", token=token, json={
                    "slug": "moscow-square", "name": "Дубликат", "city": "Москва",
                    "region": "Москва", "category": "square", "coordinates": [37.6, 55.7],
                })).status_code == 409
                assert (await call("POST", "/api/v1/admin/places", token=token, json={
                    "slug": "invalid-coords", "name": "Ошибка", "city": "Москва",
                    "region": "Москва", "category": "square", "coordinates": [200, 55.7],
                })).status_code == 422
                assert (await call("PATCH", f"/api/v1/admin/places/{place_id}", token=editor_token, json={"is_published": True})).status_code == 403
                assert (await call("PATCH", f"/api/v1/admin/places/{place_id}", token=token, json={"is_published": True})).status_code == 409
                assert (await call("PATCH", f"/api/v1/admin/places/{place_id}", token=token, json={"is_published": None})).status_code == 400

                source = await call("POST", "/api/v1/admin/sources", token=token, json={
                    "owner_name": "Test owner", "public_page_url": "https://example.org/camera",
                    "stream_url": "https://example.org/live.m3u8", "attribution": "Test owner",
                    "permission_note": "Integration test source; test database only",
                    "permission_evidence_url": "https://example.org/permission",
                    "permission_reviewed_at": "2026-09-26T00:00:00+00:00",
                    "removal_contact": "operator@example.org",
                })
                assert source.status_code == 201, source.text
                source_id = source.json()["id"]
                assert (await call("PATCH", f"/api/v1/admin/sources/{source_id}", token=token, json={"stream_url": None})).status_code == 200
                missing_url = await call("PATCH", f"/api/v1/admin/sources/{source_id}", token=token, json={"is_approved": True})
                assert missing_url.status_code == 409 and missing_url.json()["error"]["code"] == "missing_stream"
                assert (await call("PATCH", f"/api/v1/admin/sources/{source_id}", token=token, json={
                    "stream_url": "https://example.org/live.m3u8", "permission_expires_at": "2000-01-01T00:00:00+00:00",
                })).status_code == 200
                expired = await call("PATCH", f"/api/v1/admin/sources/{source_id}", token=token, json={"is_approved": True})
                assert expired.status_code == 409 and expired.json()["error"]["code"] == "permission_expired"
                assert (await call("PATCH", f"/api/v1/admin/sources/{source_id}", token=token, json={"permission_expires_at": None})).status_code == 200
                assert (await call("POST", "/api/v1/admin/sources", token=token, json={
                    "owner_name": "Blocked", "public_page_url": "https://127.0.0.1/camera",
                    "stream_url": "https://example.org/live.m3u8", "attribution": "Blocked",
                    "permission_note": "Test permission",
                })).status_code == 400
                camera = await call("POST", "/api/v1/admin/cameras", token=token, json={
                    "place_id": place_id, "source_id": source_id,
                    "name": "Тестовая камера", "playback_type": "hls",
                })
                assert camera.status_code == 201, camera.text
                camera_id = camera.json()["id"]
                assert (await call("DELETE", f"/api/v1/admin/sources/{source_id}", token=token)).status_code == 409
                assert (await call("DELETE", f"/api/v1/admin/cameras/{camera_id}", token=editor_token)).status_code == 403
                assert (await call("PATCH", f"/api/v1/admin/cameras/{camera_id}", token=token, json={"is_published": True})).status_code == 409
                assert (await call("PATCH", f"/api/v1/admin/sources/{source_id}", token=token, json={"is_approved": True})).status_code == 200
                assert (await call("PATCH", f"/api/v1/admin/sources/{source_id}", token=editor_token, json={"attribution": "Changed"})).status_code == 403
                assert (await call("PATCH", f"/api/v1/admin/cameras/{camera_id}", token=token, json={"is_published": True, "status": "online"})).status_code == 200
                assert (await call("PATCH", f"/api/v1/admin/cameras/{camera_id}", token=editor_token, json={"name": "Changed"})).status_code == 403
                assert (await call("PATCH", f"/api/v1/admin/places/{place_id}", token=token, json={"is_published": True})).status_code == 200
                assert (await call("PATCH", f"/api/v1/admin/places/{place_id}", token=editor_token, json={"address": "Changed"})).status_code == 403

                high = await call("GET", "/api/v1/places", params={"bbox": "37,55,38,56", "zoom": 10})
                assert high.status_code == 200, high.text
                assert [point["id"] for point in high.json()["points"]] == [place_id]
                category_match = await call("GET", "/api/v1/places", params={"bbox": "37,55,38,56", "zoom": 10, "category": "square"})
                assert [point["id"] for point in category_match.json()["points"]] == [place_id]
                category_empty = await call("GET", "/api/v1/places", params={"bbox": "37,55,38,56", "zoom": 10, "category": "bridge"})
                assert category_empty.json()["points"] == []
                low = await call("GET", "/api/v1/places", params={"bbox": "19,41,180,82", "zoom": 3})
                assert low.status_code == 200, low.text
                assert low.json()["clusters"][0]["camera_count"] == 1
                low_empty = await call("GET", "/api/v1/places", params={"bbox": "19,41,180,82", "zoom": 3, "category": "bridge"})
                assert low_empty.json()["clusters"] == []
                assert (await call("GET", "/api/v1/places", params={"bbox": "bad", "zoom": 10})).status_code == 400
                assert (await call("GET", "/api/v1/places", params={"bbox": "37,55,37,56", "zoom": 10})).status_code == 400
                assert (await call("GET", "/api/v1/places", params={"bbox": "19,41,180,82", "zoom": 10})).status_code == 400
                assert (await call("GET", "/api/v1/places/999999")).status_code == 404
                detail = await call("GET", f"/api/v1/places/{place_id}")
                assert detail.status_code == 200, detail.text
                assert detail.json()["cameras"][0]["playback_url"] == "https://example.org/live.m3u8"
                assert "permission_note" not in detail.text and "secret_ref" not in detail.text
                assert "Integration test source; test database only" not in detail.text
                search = await call("GET", "/api/v1/places/search", params={"q": "Москва"})
                assert search.status_code == 200, search.text
                assert any(item["kind"] == "city" for item in search.json()["suggestions"])
                assert (await call("GET", "/api/v1/places/search", params={"q": "  "})).status_code == 400

                assert (await call("PATCH", f"/api/v1/admin/cameras/{camera_id}", token=token,
                                   json={"status": "offline"})).status_code == 200
                default_map = await call("GET", "/api/v1/places", params={"bbox": "37,55,38,56", "zoom": 10})
                assert default_map.json()["points"] == []
                all_map = await call("GET", "/api/v1/places", params={
                    "bbox": "37,55,38,56", "zoom": 10, "include_offline": True,
                })
                assert all_map.json()["points"][0]["id"] == place_id
                assert all_map.json()["points"][0]["status"] == "offline"
                assert all_map.json()["points"][0]["online_count"] == 0
                all_clusters = await call("GET", "/api/v1/places", params={
                    "bbox": "19,41,180,82", "zoom": 3, "include_offline": True,
                })
                assert all_clusters.json()["clusters"][0]["status"] == "offline"
                assert (await call("GET", "/api/v1/places/search", params={"q": "Москва"})).json()["suggestions"] == []
                offline_search = await call("GET", "/api/v1/places/search", params={
                    "q": "Москва", "include_offline": True,
                })
                assert any(item["kind"] == "city" for item in offline_search.json()["suggestions"])

                eastern_ids = []
                for slug, longitude in (("eastern-edge", 179.5), ("western-edge", -179.5)):
                    eastern = await call("POST", "/api/v1/admin/places", token=token, json={
                        "slug": slug, "name": slug, "city": "Чукотка", "region": "Чукотский АО",
                        "category": "city", "coordinates": [longitude, 60],
                    })
                    assert eastern.status_code == 201, eastern.text
                    eastern_id = eastern.json()["id"]
                    eastern_ids.append(eastern_id)
                    eastern_camera = await call("POST", "/api/v1/admin/cameras", token=token, json={
                        "place_id": eastern_id, "source_id": source_id,
                        "name": f"Camera {slug}", "playback_type": "hls",
                    })
                    assert eastern_camera.status_code == 201, eastern_camera.text
                    assert (await call("PATCH", f"/api/v1/admin/cameras/{eastern_camera.json()['id']}", token=token, json={"is_published": True, "status": "online"})).status_code == 200
                    assert (await call("PATCH", f"/api/v1/admin/places/{eastern_id}", token=token, json={"is_published": True})).status_code == 200
                crossing = await call("GET", "/api/v1/places", params={"bbox": "170,40,-170,70", "zoom": 8})
                assert crossing.status_code == 200, crossing.text
                assert sum(cluster["place_count"] for cluster in crossing.json()["clusters"]) == 2
                crossing_points = await call("GET", "/api/v1/places", params={"bbox": "170,50,-170,70", "zoom": 9})
                assert crossing_points.status_code == 200, crossing_points.text
                assert {item["id"] for item in crossing_points.json()["points"]} == set(eastern_ids)

                csv_text = "slug,name,city,region,category,longitude,latitude\nkazan-center,Центр Казани,Казань,Татарстан,square,49.12,55.79\n"
                preview = await call("POST", "/api/v1/admin/import/preview", token=editor_token, json={"format": "csv", "content": csv_text})
                assert preview.status_code == 200, preview.text
                assert preview.json()["items"][0]["action"] == "create"
                imported = await call("POST", "/api/v1/admin/import/apply", token=token, json={"format": "csv", "content": csv_text})
                assert imported.status_code == 200, imported.text
                assert imported.json()["created"] == 1
                repeat = await call("POST", "/api/v1/admin/import/apply", token=token, json={"format": "csv", "content": csv_text})
                assert repeat.status_code == 200 and repeat.json()["updated"] == 1
                draft_places = (await call("GET", "/api/v1/admin/places", token=token)).json()
                kazan_id = next(item["id"] for item in draft_places if item["slug"] == "kazan-center")
                assert (await call("DELETE", f"/api/v1/admin/places/{kazan_id}", token=token)).status_code == 204
                assert (await call("GET", f"/api/v1/admin/places/{kazan_id}", token=token)).status_code == 404
                recreated = await call("POST", "/api/v1/admin/import/apply", token=token, json={"format": "csv", "content": csv_text})
                assert recreated.status_code == 200 and recreated.json()["created"] == 1
                duplicate_rows = csv_text + "kazan-center,Ещё центр,Казань,Татарстан,square,49.12,55.79\n"
                bad_preview = await call("POST", "/api/v1/admin/import/preview", token=token, json={"format": "csv", "content": duplicate_rows})
                assert bad_preview.status_code == 200 and bad_preview.json()["errors"]
                assert (await call("POST", "/api/v1/admin/import/apply", token=token, json={"format": "csv", "content": duplicate_rows})).status_code == 400
                cameras_csv = (
                    "slug,name,city,region,category,longitude,latitude,camera_name,playback_type,owner_name,public_page_url,stream_url,attribution,permission_note\n"
                    "two-cameras,Две камеры,Сочи,Краснодарский край,city,39.72,43.6,Первая,hls,Test owner,https://example.org/first,https://example.org/first.m3u8,Test owner,Test permission only\n"
                    "two-cameras,Две камеры,Сочи,Краснодарский край,city,39.72,43.6,Вторая,hls,Test owner,https://example.org/second,https://example.org/second.m3u8,Test owner,Test permission only\n"
                )
                multi_preview = await call("POST", "/api/v1/admin/import/preview", token=token, json={"format": "csv", "content": cameras_csv})
                assert multi_preview.status_code == 200 and not multi_preview.json()["errors"]
                assert [item["action"] for item in multi_preview.json()["items"]] == ["create", "update"]
                multi_import = await call("POST", "/api/v1/admin/import/apply", token=token, json={"format": "csv", "content": cameras_csv})
                assert multi_import.status_code == 200, multi_import.text
                assert multi_import.json()["draft_cameras"] == 2
                geojson = (ROOT_DIR / "demo" / "places.geojson").read_text(encoding="utf-8")
                geo_preview = await call("POST", "/api/v1/admin/import/preview", token=token, json={"format": "geojson", "content": geojson})
                assert geo_preview.status_code == 200 and not geo_preview.json()["errors"]
                assert len(geo_preview.json()["items"]) == 3
                assert (await call("POST", "/api/v1/admin/import/apply", token=token, json={"format": "geojson", "content": geojson})).status_code == 200
                assert (await call("GET", "/api/v1/places/search", params={"q": "Казань"})).json()["suggestions"] == []

                secret_source = await call("POST", "/api/v1/admin/sources", token=token, json={
                    "owner_name": "Secret owner", "public_page_url": "https://example.org/secret",
                    "stream_url": "https://example.org/private.m3u8", "secret_ref": "PRIVATE_STREAM_KEY",
                    "attribution": "Secret owner", "permission_note": "Permission for gateway only",
                    "permission_evidence_url": "https://example.org/permission",
                    "permission_reviewed_at": "2026-09-26T00:00:00+00:00",
                    "removal_contact": "operator@example.org",
                })
                assert secret_source.status_code == 201, secret_source.text
                secret_id = secret_source.json()["id"]
                assert (await call("PATCH", f"/api/v1/admin/sources/{secret_id}", token=token, json={"is_approved": True})).status_code == 200
                secret_camera = await call("POST", "/api/v1/admin/cameras", token=token, json={
                    "place_id": place_id, "source_id": secret_id,
                    "name": "Secret stream", "playback_type": "hls",
                })
                assert secret_camera.status_code == 201, secret_camera.text
                assert (await call("PATCH", f"/api/v1/admin/cameras/{secret_camera.json()['id']}", token=token, json={"is_published": True})).status_code == 409
                assert "PRIVATE_STREAM_KEY" not in (await call("GET", f"/api/v1/places/{place_id}")).text
                monkeypatch.setattr(get_settings(), "media_gateway_public_base", "https://media.example.org")
                gateway_url = "https://media.example.org/camera1/index.m3u8"
                update = await call("PATCH", f"/api/v1/admin/sources/{secret_id}", token=token,
                                    json={"stream_url": gateway_url, "secret_ref": "LIVEMAP_RTSP_UPSTREAM"})
                assert update.status_code == 200, update.text
                assert (await call("PATCH", f"/api/v1/admin/sources/{secret_id}", token=token,
                                   json={"is_approved": True})).status_code == 200
                assert (await call("PATCH", f"/api/v1/admin/cameras/{secret_camera.json()['id']}", token=token,
                                   json={"is_published": True, "status": "online"})).status_code == 200
                # Worker confirmation, not a manual online toggle, makes playback available.
                async with factory() as session:
                    gateway_camera = await session.get(Camera, secret_camera.json()['id'])
                    gateway_camera.last_checked_at = datetime.now(timezone.utc)
                    await session.commit()
                public = await call("GET", f"/api/v1/places/{place_id}")
                assert gateway_url in public.text and "LIVEMAP_RTSP_UPSTREAM" not in public.text
                mapped = await call("GET", "/api/v1/places", params={"bbox": "37,55,38,56", "zoom": 12})
                assert any(item["id"] == place_id for item in mapped.json()["points"])
                monkeypatch.setattr(get_settings(), "media_gateway_public_base", None)
                assert gateway_url not in (await call("GET", f"/api/v1/places/{place_id}")).text
                assert (await call("DELETE", f"/api/v1/admin/cameras/{secret_camera.json()['id']}", token=token)).status_code == 204
                assert (await call("DELETE", f"/api/v1/admin/sources/{secret_id}", token=token)).status_code == 204

                query_source = await call("POST", "/api/v1/admin/sources", token=token, json={
                    "owner_name": "Query owner", "public_page_url": "https://example.org/query",
                    "stream_url": "https://example.org/live.m3u8?session=temporary",
                    "attribution": "Query owner", "permission_note": "Permission for gateway only",
                    "permission_evidence_url": "https://example.org/permission",
                    "permission_reviewed_at": "2026-09-26T00:00:00+00:00",
                    "removal_contact": "operator@example.org",
                })
                assert query_source.status_code == 201, query_source.text
                query_id = query_source.json()["id"]
                assert (await call("PATCH", f"/api/v1/admin/sources/{query_id}", token=token, json={"is_approved": True})).status_code == 200
                query_camera = await call("POST", "/api/v1/admin/cameras", token=token, json={
                    "place_id": place_id, "source_id": query_id,
                    "name": "Query stream", "playback_type": "hls",
                })
                assert query_camera.status_code == 201, query_camera.text
                assert (await call("PATCH", f"/api/v1/admin/cameras/{query_camera.json()['id']}", token=token, json={"is_published": True})).status_code == 409
                assert "session=temporary" not in (await call("GET", f"/api/v1/places/{place_id}")).text

                for _ in range(30):
                    response = await call("GET", "/api/v1/places/search", params={"q": "Москва"})
                    if response.status_code == 429:
                        break
                    assert response.status_code == 200
                else:
                    pytest.fail("Search did not enforce its 30 request limit")

                audit = await call("GET", "/api/v1/admin/audit", token=token)
                assert audit.status_code == 200 and audit.json()
                changed_source = await call(
                    "PATCH", f"/api/v1/admin/sources/{source_id}", token=token,
                    json={"stream_url": "https://example.org/replaced.m3u8"},
                )
                assert changed_source.status_code == 200 and not changed_source.json()["is_approved"]
                changed_camera = await call("GET", f"/api/v1/admin/cameras/{camera_id}", token=token)
                assert not changed_camera.json()["is_published"]
                assert changed_camera.json()["status"] == "unknown"
                assert (await call("PATCH", f"/api/v1/admin/sources/{source_id}", token=token, json={"is_approved": True})).status_code == 200
                assert not (await call("GET", f"/api/v1/admin/cameras/{camera_id}", token=token)).json()["is_published"]
                assert (await call("POST", "/api/v1/admin/logout", token=token)).status_code == 204
                assert (await call("GET", "/api/v1/admin/me", token=token)).status_code == 401
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    asyncio.run(run())


def test_report_and_prolonged_outage(test_database_url, monkeypatch) -> None:
    async def run() -> None:
        engine = create_async_engine(test_database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def test_session():
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = test_session
        monkeypatch.setattr("livemap.worker.get_session_factory", lambda: factory)
        try:
            async with factory() as session:
                place = Place(
                    slug="monitor-test", name="Monitor Test", city="Москва", region="Москва",
                    category="street", geometry=point(37.6, 55.7), is_published=True,
                )
                source = Source(
                    owner_name="Test operator", public_page_url="https://example.org/live",
                    stream_url="https://example.org/live.m3u8", attribution="Test operator",
                    permission_note="Test permission for integration test", is_approved=True,
                )
                session.add_all((place, source))
                await session.flush()
                camera = Camera(
                    place_id=place.id, source_id=source.id, name="Test camera",
                    playback_type="hls", status="unknown", is_published=True,
                )
                session.add(camera)
                session.add(AdminUser(
                    username="monitor-admin", password_hash=hash_password("test-password-123"), role="admin",
                ))
                await session.commit()
                camera_id, source_id = camera.id, source.id

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                report = await client.post(
                    f"/api/v1/cameras/{camera_id}/reports",
                    json={"reason": "rights", "details": "Please review the permission for this camera."},
                )
                assert report.status_code == 201, report.text
                login = await client.post("/api/v1/admin/login", json={
                    "username": "monitor-admin", "password": "test-password-123",
                })
                token = login.json()["access_token"]
                headers = {"Authorization": f"Bearer {token}"}
                queue = await client.get("/api/v1/admin/reports", headers=headers)
                assert queue.status_code == 200
                assert any(item["id"] == report.json()["id"] for item in queue.json())
                resolved = await client.patch(
                    f"/api/v1/admin/reports/{report.json()['id']}", headers=headers,
                    json={"resolution": "Camera removed pending permission review.", "unpublish_camera": True},
                )
                assert resolved.status_code == 200, resolved.text
                operations = await client.get("/api/v1/admin/operations", headers=headers)
                assert operations.status_code == 200, operations.text
                assert operations.json()["open_reports"] == 0
                assert operations.json()["worker_stale"] is True

            async with factory() as session:
                camera = await session.get(Camera, camera_id)
                assert not camera.is_published and camera.unpublished_reason == "report"
                camera.is_published = True
                await session.commit()

            due = DueCamera(camera_id, source_id, "hls", "https://example.org/live.m3u8", None, False)
            for _ in range(12):
                await save_check(due, ProbeResult("offline", "connection_failed", 100))
            async with factory() as session:
                camera = await session.get(Camera, camera_id)
                assert not camera.is_published
                assert camera.status == "offline"
                assert camera.consecutive_failures == 12
                assert camera.unpublished_reason == "prolonged_outage"
                assert len((await session.execute(
                    select(CameraCheck).where(CameraCheck.camera_id == camera_id)
                )).scalars().all()) == 12
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    asyncio.run(run())


def test_dense_map_is_bounded(test_database_url, monkeypatch) -> None:
    async def run() -> None:
        engine = create_async_engine(test_database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def test_session():
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = test_session
        try:
            now = datetime.now(timezone.utc)
            async with factory() as session:
                source = Source(
                    owner_name="Load test", public_page_url="https://example.org/load",
                    stream_url="https://example.org/load.m3u8", attribution="Load test",
                    permission_note="Isolated synthetic test", is_approved=True,
                    permission_evidence_url="https://example.org/permission",
                    permission_reviewed_at=now, removal_contact="operator@example.org",
                )
                session.add(source)
                await session.flush()
                for index in range(550):
                    place = Place(
                        slug=f"dense-{index}", name=f"Dense place {index}",
                        city="Москва", region="Москва", category="square",
                        geometry=point(37.5 + (index % 25) * 0.001,
                                       55.7 + (index // 25) * 0.001),
                        is_published=True,
                    )
                    session.add(place)
                    await session.flush()
                    session.add(Camera(
                        place_id=place.id, source_id=source.id, name=f"Camera {index}",
                        playback_type="hls", status="online", is_published=True,
                        last_checked_at=now,
                    ))
                await session.commit()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/api/v1/places", params={"bbox": "37,55,38,56", "zoom": 10})
                assert response.status_code == 200, response.text
                assert len(response.json()["points"]) == 500
                assert response.json()["truncated"] is True
                assert len(response.content) < 250_000
                clusters = await client.get("/api/v1/places", params={"bbox": "19,41,180,82", "zoom": 3})
                assert clusters.status_code == 200
                assert sum(item["place_count"] for item in clusters.json()["clusters"]) >= 550
                health = await client.get("/api/v1/health/cameras")
                assert health.status_code == 200
                assert health.json()["status"] == "ok" and health.json()["published"] >= 550
                assert set(health.json()) == {"status", "published", "online", "stale", "latest_check_at"}
                async def measure(zoom):
                    start = time.perf_counter()
                    result = await client.get("/api/v1/places", params={"bbox": "37,55,38,56", "zoom": zoom})
                    assert result.status_code == 200
                    return (time.perf_counter() - start) * 1000
                sequential = [await measure(10) for _ in range(10)]
                concurrent = await asyncio.gather(*(measure(10 if index % 2 else 3) for index in range(20)))
                print({"dense_points": 550, "returned_points": 500, "response_bytes": len(response.content),
                       "bbox_p50_ms": round(statistics.median(sequential), 2),
                       "bbox_max_ms": round(max(sequential), 2),
                       "concurrent_requests": 20, "concurrent_max_ms": round(max(concurrent), 2)})
            active = peak = batches = checked = 0

            class LoadProbe:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args):
                    pass

                def __init__(self, _origin):
                    pass

                async def check(self, *_args, **_kwargs):
                    nonlocal active, peak
                    active += 1
                    peak = max(peak, active)
                    try:
                        await asyncio.sleep(0.01)
                        return ProbeResult("online", "ok", 10)
                    finally:
                        active -= 1

            monkeypatch.setattr("livemap.worker.get_session_factory", lambda: factory)
            monkeypatch.setattr("livemap.worker.CameraProbe", LoadProbe)
            started = time.perf_counter()
            while count := await run_once():
                batches += 1
                checked += count
                assert batches < 1000, "Due cameras must leave the current check queue"
            async with factory() as session:
                saved = (await session.execute(text(
                    "SELECT count(*) FROM camera_checks JOIN cameras ON camera_checks.camera_id=cameras.id WHERE cameras.source_id=:source_id"
                ), {"source_id": source.id})).scalar_one()
            assert saved == 550
            assert peak <= min(max(get_settings().camera_check_concurrency, 1), 16)
            print({"worker_catalog": 550, "checked": checked, "batches": batches,
                   "peak_concurrency": peak, "seconds": round(time.perf_counter() - started, 3),
                   "upstream": "synthetic 10ms probe; real PostGIS claim/save operations"})
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    asyncio.run(run())
