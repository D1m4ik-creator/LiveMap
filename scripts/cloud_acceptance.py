"""Run the authorized admin/public acceptance cycle using disposable records.

Set LIVEMAP_ADMIN_PASSWORD privately; no credentials are persisted or printed.
The existing approved source is read only. Created records are removed in finally.
"""

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx

from livemap.services.camera_probe import CameraProbe


async def main() -> None:
    origin = "https://livemap-demo.onrender.com"
    created: list[tuple[str, int]] = []
    proof = {"origin": origin, "steps": []}
    async with httpx.AsyncClient(base_url=origin, timeout=60) as client:
        token = None
        async def call(method: str, path: str, *, expected=200, **kwargs):
            headers = {"Authorization": "Bearer " + token} if token else {}
            response = await client.request(method, "/api/v1" + path, headers=headers, **kwargs)
            if response.status_code != expected:
                raise RuntimeError(f"{method} {path}: HTTP {response.status_code}, expected {expected}")
            return response.json() if response.content else None

        try:
            login = await call("POST", "/admin/login", json={"username": "admin", "password": os.environ["LIVEMAP_ADMIN_PASSWORD"]})
            token = login["access_token"]
            assert (await call("GET", "/admin/me"))["role"] == "admin"
            proof["steps"].append("login and persisted role")
            original = await call("GET", "/admin/sources/16")
            assert original["is_approved"] and not original.get("secret_ref")
            async with CameraProbe(origin) as probe:
                await probe.hls(original["stream_url"])
            proof["steps"].append("real source HLS manifest, CORS and segment check")
            place = await call("POST", "/admin/places", expected=201, json={
                "slug": "acceptance-" + uuid4().hex[:12], "name": "Приёмочный тест — временная точка",
                "city": "Красноярск", "region": "Красноярский край", "category": "street", "coordinates": [92.8274316, 55.9825039],
            })
            created.append(("places", place["id"]))
            fields = ("owner_name", "public_page_url", "stream_url", "attribution", "permission_note", "permission_evidence_url", "permission_reviewed_at", "permission_expires_at", "removal_contact", "embed_host")
            source = await call("POST", "/admin/sources", expected=201, json={key: original[key] for key in fields})
            created.append(("sources", source["id"]))
            camera = await call("POST", "/admin/cameras", expected=201, json={"place_id": place["id"], "source_id": source["id"], "name": "Приёмочный HLS-тест", "playback_type": "hls"})
            created.append(("cameras", camera["id"]))
            await call("GET", f"/places/{place['id']}", expected=404)
            await call("PATCH", f"/admin/cameras/{camera['id']}", expected=409, json={"is_published": True})
            proof["steps"].append("draft absent from public API; unapproved source blocks publication")
            await call("PATCH", f"/admin/sources/{source['id']}", json={"is_approved": True})
            await call("PATCH", f"/admin/cameras/{camera['id']}", json={"is_published": True, "status": "online"})
            await call("PATCH", f"/admin/places/{place['id']}", json={"is_published": True})
            public = await call("GET", f"/places/{place['id']}")
            assert public["cameras"][0]["playback_url"] == original["stream_url"]
            proof["steps"].append("approval, publication and public playback metadata")
            await call("PATCH", f"/admin/cameras/{camera['id']}", json={"name": "Приёмочный HLS-тест после сохранения"})
            assert (await call("GET", "/admin/me"))["role"] == "admin"
            await call("PATCH", f"/admin/cameras/{camera['id']}", json={"is_published": False})
            await call("GET", f"/places/{place['id']}", expected=404)
            proof["steps"].append("save preserves session; unpublication removes public place")
            audit = await call("GET", "/admin/audit?limit=100")
            assert any(item["entity_id"] == camera["id"] and item["entity_type"] == "camera" for item in audit)
            proof["steps"].append("cloud audit records present")
        finally:
            if token:
                for kind, item_id in reversed(created):
                    await call("DELETE", f"/admin/{kind}/{item_id}", expected=204)
                await call("POST", "/admin/logout", expected=204)
                await call("GET", "/admin/me", expected=401)
                proof["steps"].append("created fixtures removed; logout revokes session")
            Path("backups").mkdir(exist_ok=True)
            Path("backups/cloud-acceptance.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(proof, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
