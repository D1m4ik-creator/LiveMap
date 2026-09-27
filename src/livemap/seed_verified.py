"""Publish reviewed public embeds after a fresh live probe.

The browser verification time is stored in the committed catalog. Re-running this
command cannot extend it or republish a camera removed after a complaint.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import func, select

from livemap.core.config import ROOT_DIR, get_settings
from livemap.core.engine import close_engine, get_session_factory
from livemap.db.models import AuditEvent, Camera, CameraCheck, CameraReport, Place, Source
from livemap.services.camera_probe import CameraProbe, rutube_embed_id
from livemap.services.source_rules import (
    ensure_camera_publishable, public_iframe_query_allowed, validate_source_metadata,
)


REVIEWED_IPEYE_CAMERAS = {
    "Панорама экопарка": "243eafa8f63049408a996398bec79228",
    "Парковка экопарка": "75085eeed28446fd9eeb2fbb421c5d20",
}


def reviewed_embed(item: dict, now: datetime) -> datetime:
    if item.get("publish_reviewed") is not True:
        raise ValueError("Camera is not reviewed for publication")
    verified_at = datetime.fromisoformat(item["embed_verified_at"])
    if verified_at.tzinfo is None or not now - timedelta(days=7) < verified_at <= now + timedelta(minutes=5):
        raise ValueError("Browser verification is missing or older than seven days")
    video_id = rutube_embed_id(item["stream_url"])
    if video_id is not None:
        if (
            item["embed_host"] != "rutube.ru"
            or item["public_page_url"] != f"https://rutube.ru/live/video/{video_id}/"
            or item["permission_evidence_url"] != "https://rutube.ru/info/embed/"
        ):
            raise ValueError("Reviewed source must use the public RUTUBE embed and its policy")
    elif item.get("slug") == "narzan-valley-ecopark":
        parsed = urlsplit(item["stream_url"])
        dev = parse_qs(parsed.query).get("dev", [None])
        if (
            item["embed_host"] != "ipeye.ru"
            or not public_iframe_query_allowed(item["stream_url"], "ipeye.ru")
            or dev != [REVIEWED_IPEYE_CAMERAS.get(item["camera_name"])]
            or item["public_page_url"] != "https://dolinanarzanov.ru/new-online"
            or item["permission_evidence_url"] != "https://www.ipeye.ru/translyaciya-video-na-sajt"
        ):
            raise ValueError("Reviewed source must use the owner's public IPEYE embed")
    else:
        raise ValueError("Reviewed source must have explicit provider evidence")
    return verified_at


async def publish() -> int:
    candidates = json.loads((ROOT_DIR / "demo" / "camera_candidates.json").read_text(encoding="utf-8"))
    settings = get_settings()
    now = datetime.now(timezone.utc)
    published = 0
    async with get_session_factory()() as session, CameraProbe(settings.public_origin) as probe:
        for item in candidates:
            if item.get("publish_reviewed") is not True:
                continue
            verified_at = reviewed_embed(item, now)
            place = (await session.execute(
                select(Place).where(Place.slug == item["slug"]).with_for_update()
            )).scalar_one_or_none()
            if place is None:
                raise ValueError(f"Seed candidate {item['slug']} before publication")
            coordinates = (await session.execute(
                select(func.ST_X(Place.geometry), func.ST_Y(Place.geometry)).where(Place.id == place.id)
            )).one()
            record = (await session.execute(
                select(Camera, Source).join(Source, Source.id == Camera.source_id)
                .where(Camera.place_id == place.id, Camera.name == item["camera_name"])
                .with_for_update(of=(Camera, Source))
            )).one_or_none()
            if record is None:
                raise ValueError(f"Camera {item['slug']} was not found")
            camera, source = record
            if source.is_approved and camera.is_published and place.is_published:
                continue
            if source.is_approved or camera.is_published:
                raise ValueError(f"Camera {item['slug']} was changed after review; manual action required")
            if (await session.execute(
                select(CameraReport.id).where(CameraReport.camera_id == camera.id, CameraReport.status == "open")
            )).first():
                raise ValueError(f"Camera {item['slug']} has an open report")
            expected = (
                place.name == item["name"]
                and place.city == item["city"]
                and place.region == item["region"]
                and place.address == item["address"]
                and place.category == item["category"]
                and all(abs(float(actual) - wanted) < 0.000001 for actual, wanted in zip(coordinates, item["coordinates"]))
                and source.permission_reviewed_at == datetime.fromisoformat(item["permission_reviewed_at"])
                and source.permission_expires_at is None
                and source.secret_ref is None
                and source.owner_name == item["owner_name"]
                and source.public_page_url == item["public_page_url"]
                and source.stream_url == item["stream_url"]
                and source.embed_host == item["embed_host"]
                and source.attribution == item["attribution"]
                and source.permission_note == item["permission_note"]
                and source.permission_evidence_url == item["permission_evidence_url"]
                and source.removal_contact == item["removal_contact"]
                and camera.playback_type == item["playback_type"]
                and camera.unpublished_reason is None
            )
            if not expected:
                raise ValueError(f"Camera {item['slug']} no longer matches the reviewed catalog")
            validate_source_metadata(source)
            result = await probe.check(
                camera.playback_type, source.stream_url,
                embed_host=source.embed_host, embed_verified=True,
            )
            if result.status != "online":
                raise ValueError(f"Camera {item['slug']} failed the live probe: {result.code}")
            source.is_approved = True
            camera.embed_verified_at = verified_at
            ensure_camera_publishable(camera, source)
            camera.is_published = True
            camera.status = "online"
            camera.last_checked_at = now
            camera.last_success_at = now
            camera.last_error_code = None
            camera.next_check_at = now + timedelta(seconds=max(60, settings.camera_check_interval_seconds))
            place.is_published = True
            session.add(CameraCheck(
                camera_id=camera.id, checked_at=now, result="online", code="ok", duration_ms=result.duration_ms,
            ))
            for action, entity_type, entity_id in (
                ("seed_approve", "source", source.id),
                ("seed_publish", "camera", camera.id),
                ("seed_publish", "place", place.id),
            ):
                session.add(AuditEvent(
                    actor_id=None, action=action, entity_type=entity_type, entity_id=entity_id,
                    summary=f"Reviewed public embed {item['slug']} published from committed evidence",
                ))
            published += 1
        await session.commit()
    return published


async def run() -> None:
    try:
        count = await publish()
        print(f"Published {count} reviewed live cameras")
    finally:
        await close_engine()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
