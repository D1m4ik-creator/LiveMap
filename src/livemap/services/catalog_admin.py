from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from livemap.api.errors import APIError
from livemap.api.schemas.admin import PlaceAdminOutput
from livemap.db.models import AdminUser, AuditEvent, Camera, Place, Source
from livemap.services.source_rules import ensure_camera_publishable, validate_url


def point(longitude: float, latitude: float):
    return func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326)


async def place_output(session: AsyncSession, place: Place) -> PlaceAdminOutput:
    row = (
        await session.execute(
            select(func.ST_X(Place.geometry), func.ST_Y(Place.geometry)).where(Place.id == place.id)
        )
    ).one()
    return PlaceAdminOutput(
        id=place.id, slug=place.slug, name=place.name, address=place.address,
        city=place.city, region=place.region, category=place.category,
        coordinates=(float(row[0]), float(row[1])), is_published=place.is_published,
        created_at=place.created_at, updated_at=place.updated_at,
    )


def audit(session: AsyncSession, actor: AdminUser, action: str, entity_type: str, entity_id: int | None, summary: str) -> None:
    session.add(AuditEvent(
        actor_id=actor.id, action=action, entity_type=entity_type,
        entity_id=entity_id, summary=summary,
    ))


async def commit_or_conflict(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise APIError("conflict", "Entity conflicts with existing catalog data", 409) from exc


async def require_place(session: AsyncSession, place_id: int) -> Place:
    place = await session.get(Place, place_id)
    if place is None:
        raise APIError("place_not_found", "Place not found", 404)
    return place


async def require_source(session: AsyncSession, source_id: int) -> Source:
    source = await session.get(Source, source_id)
    if source is None:
        raise APIError("source_not_found", "Source not found", 404)
    return source


async def require_camera(session: AsyncSession, camera_id: int) -> Camera:
    camera = await session.get(Camera, camera_id)
    if camera is None:
        raise APIError("camera_not_found", "Camera not found", 404)
    return camera


async def ensure_place_publishable(session: AsyncSession, place: Place) -> None:
    rows = (
        await session.execute(
            select(Camera, Source)
            .join(Source, Source.id == Camera.source_id)
            .where(Camera.place_id == place.id, Camera.is_published.is_(True))
        )
    ).all()
    if not rows:
        raise APIError("no_published_camera", "Publish a camera before its place", 409)
    for camera, source in rows:
        try:
            ensure_camera_publishable(camera, source)
            return
        except APIError:
            continue
    raise APIError("no_available_source", "Place has no publishable camera", 409)


def ensure_camera_source_type(camera_type: str, source: Source) -> None:
    if not source.stream_url:
        return
    validate_url(source.stream_url, {"rtsp"} if camera_type == "rtsp" else {"https"})
