"""Periodic camera checks. Run as a separate process: livemap-worker."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select

from livemap.core.config import get_settings
from livemap.core.engine import close_engine, get_session_factory
from livemap.db.models import AuditEvent, Camera, CameraCheck, Source
from livemap.services.camera_probe import CameraProbe, ProbeResult

logger = logging.getLogger("livemap.worker")


@dataclass(frozen=True)
class DueCamera:
    id: int
    source_id: int
    playback_type: str
    url: str
    embed_host: str | None
    embed_verified: bool


async def unpublish_expired() -> int:
    now = datetime.now(timezone.utc)
    async with get_session_factory()() as session:
        rows = (await session.execute(
            select(Camera, Source).join(Source, Source.id == Camera.source_id)
            .where(Camera.is_published.is_(True), or_(
                Source.is_approved.is_(False),
                Source.permission_evidence_url.is_(None),
                Source.permission_reviewed_at.is_(None),
                Source.removal_contact.is_(None),
                and_(Source.permission_expires_at.is_not(None), Source.permission_expires_at <= now),
                and_(Camera.valid_until.is_not(None), Camera.valid_until <= now),
            ))
            .with_for_update(of=Camera, skip_locked=True)
        )).all()
        for camera, source in rows:
            camera.is_published = False
            camera.status = "offline"
            camera.unpublished_reason = (
                "permission_revoked" if not source.is_approved else
                "rights_incomplete" if not (source.permission_evidence_url and source.permission_reviewed_at and source.removal_contact) else
                "permission_expired" if source.permission_expires_at and source.permission_expires_at <= now else
                "camera_expired"
            )
            session.add(AuditEvent(
                actor_id=None, action="auto_unpublish", entity_type="camera", entity_id=camera.id,
                summary=f"Camera {camera.id} unpublished: {camera.unpublished_reason}",
            ))
        await session.commit()
        return len(rows)


async def claim_due(limit: int, interval: int) -> list[DueCamera]:
    now = datetime.now(timezone.utc)
    async with get_session_factory()() as session:
        rows = (await session.execute(
            select(Camera, Source).join(Source, Source.id == Camera.source_id)
            .where(
                Camera.is_published.is_(True), Source.is_approved.is_(True),
                Source.permission_evidence_url.is_not(None),
                Source.permission_reviewed_at.is_not(None),
                Source.removal_contact.is_not(None),
                or_(Source.permission_expires_at.is_(None), Source.permission_expires_at > now),
                Source.stream_url.is_not(None),
                or_(Camera.next_check_at.is_(None), Camera.next_check_at <= now),
            )
            .order_by(Camera.next_check_at.nullsfirst(), Camera.id)
            .limit(limit)
            .with_for_update(of=Camera, skip_locked=True)
        )).all()
        due = []
        for camera, source in rows:
            camera.next_check_at = now + timedelta(seconds=interval)
            due.append(DueCamera(
                id=camera.id, source_id=source.id, playback_type=camera.playback_type,
                url=source.stream_url, embed_host=source.embed_host,
                embed_verified=bool(camera.embed_verified_at and camera.embed_verified_at > now - timedelta(days=7)),
            ))
        await session.commit()
        return due


async def save_check(due: DueCamera, result: ProbeResult) -> None:
    now = datetime.now(timezone.utc)
    async with get_session_factory()() as session:
        camera = (await session.execute(
            select(Camera).where(Camera.id == due.id).with_for_update()
        )).scalar_one_or_none()
        if camera is None or not camera.is_published or camera.source_id != due.source_id:
            return
        source = await session.get(Source, due.source_id)
        if source is None or source.stream_url != due.url or not source.is_approved:
            return
        camera.last_checked_at = now
        camera.status = result.status
        camera.last_error_code = None if result.status == "online" else result.code
        if result.status == "online":
            camera.last_success_at = now
            camera.consecutive_failures = 0
        elif result.status == "offline":
            camera.consecutive_failures += 1
            if camera.consecutive_failures >= 12 and (
                camera.last_success_at is None or camera.last_success_at <= now - timedelta(hours=24)
            ):
                camera.is_published = False
                camera.unpublished_reason = "prolonged_outage"
                session.add(AuditEvent(
                    actor_id=None, action="auto_unpublish", entity_type="camera", entity_id=camera.id,
                    summary=f"Camera {camera.id} unpublished after prolonged outage",
                ))
        session.add(CameraCheck(
            camera_id=due.id, checked_at=now, result=result.status,
            code=result.code, duration_ms=result.duration_ms,
        ))
        await session.commit()
        logger.info(json.dumps({"event": "camera_check", "camera_id": due.id,
                                "status": result.status, "code": result.code,
                                "duration_ms": result.duration_ms}))


async def check_due(probe: CameraProbe, camera: DueCamera) -> None:
    try:
        result = await probe.check(
            camera.playback_type, camera.url,
            embed_host=camera.embed_host, embed_verified=camera.embed_verified,
        )
    except Exception as exc:
        logger.error(json.dumps({"event": "camera_probe_error", "camera_id": camera.id,
                                 "exception_type": type(exc).__name__}))
        result = ProbeResult("unknown", "probe_error", 0)
    await save_check(camera, result)


async def run_once() -> int:
    settings = get_settings()
    unpublished = await unpublish_expired()
    if unpublished:
        logger.warning(json.dumps({"event": "expired_cameras_unpublished", "count": unpublished}))
    concurrency = max(1, min(settings.camera_check_concurrency, 16))
    interval = max(60, settings.camera_check_interval_seconds)
    due = await claim_due(concurrency, interval)
    if not due:
        return 0
    async with CameraProbe(settings.public_origin) as probe:
        await asyncio.gather(*(check_due(probe, camera) for camera in due))
    logger.info(json.dumps({"event": "camera_check_batch", "count": len(due)}))
    return len(due)


async def serve(once: bool) -> None:
    try:
        if once:
            while await run_once():
                pass
        else:
            while True:
                await run_once()
                await asyncio.sleep(10)
    finally:
        await close_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description="Check published LiveMap cameras")
    parser.add_argument("--once", action="store_true", help="Check currently due cameras and exit")
    args = parser.parse_args()
    asyncio.run(serve(args.once))


if __name__ == "__main__":
    main()
