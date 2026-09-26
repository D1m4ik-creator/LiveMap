from datetime import datetime, timezone

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from livemap.api.schemas.catalog import (
    MapCluster,
    MapPoint,
    MapResponse,
    PlaceDetail,
    PublicCamera,
    SearchResponse,
    SearchSuggestion,
)
from livemap.db.models import Camera, Place, Source
from livemap.services.geo import BBox


MAX_MAP_ITEMS = 500


def approved_source(now: datetime):
    return and_(
        Source.is_approved.is_(True),
        or_(Source.permission_expires_at.is_(None), Source.permission_expires_at > now),
    )


def available_camera(now: datetime):
    return and_(
        Camera.is_published.is_(True),
        Camera.status == "online",
        Camera.playback_type.in_(("hls", "iframe")),
        or_(Camera.valid_until.is_(None), Camera.valid_until > now),
        approved_source(now),
        Source.stream_url.is_not(None),
        Source.stream_url.like("https://%"),
        ~Source.stream_url.contains("?"),
        Source.secret_ref.is_(None),
    )


def available_count(now: datetime):
    return (
        select(func.count(Camera.id))
        .select_from(Camera)
        .join(Source, Source.id == Camera.source_id)
        .where(Camera.place_id == Place.id, available_camera(now))
        .correlate(Place)
        .scalar_subquery()
    )


def in_bbox(bbox: BBox):
    if bbox.crosses_antimeridian:
        return or_(
            func.ST_Intersects(
                Place.geometry, func.ST_MakeEnvelope(bbox.west, bbox.south, 180, bbox.north, 4326)
            ),
            func.ST_Intersects(
                Place.geometry, func.ST_MakeEnvelope(-180, bbox.south, bbox.east, bbox.north, 4326)
            ),
        )
    return func.ST_Intersects(
        Place.geometry, func.ST_MakeEnvelope(bbox.west, bbox.south, bbox.east, bbox.north, 4326)
    )


async def map_items(session: AsyncSession, bbox: BBox, zoom: int) -> MapResponse:
    now = datetime.now(timezone.utc)
    count = available_count(now)
    longitude = func.ST_X(Place.geometry)
    latitude = func.ST_Y(Place.geometry)
    where = (Place.is_published.is_(True), in_bbox(bbox), count > 0)

    if zoom >= 9:
        query = (
            select(Place.id, Place.slug, Place.name, Place.city, Place.category, longitude, latitude, count)
            .where(*where)
            .order_by(Place.id)
            .limit(MAX_MAP_ITEMS + 1)
        )
        rows = (await session.execute(query)).all()
        points = [
            MapPoint(
                id=row[0], slug=row[1], name=row[2], city=row[3], category=row[4],
                coordinates=(float(row[5]), float(row[6])), camera_count=row[7],
            )
            for row in rows[:MAX_MAP_ITEMS]
        ]
        return MapResponse(mode="points", points=points, truncated=len(rows) > MAX_MAP_ITEMS)

    cell = 360 / (2 ** zoom * 8)
    gx = func.floor((longitude + 180) / cell)
    gy = func.floor((latitude + 90) / cell)
    query = (
        select(gx, gy, func.avg(longitude), func.avg(latitude), func.count(Place.id), func.sum(count))
        .where(*where)
        .group_by(gx, gy)
        .order_by(gx, gy)
        .limit(MAX_MAP_ITEMS + 1)
    )
    rows = (await session.execute(query)).all()
    clusters = [
        MapCluster(
            id=f"{zoom}:{int(row[0])}:{int(row[1])}",
            coordinates=(float(row[2]), float(row[3])),
            place_count=row[4], camera_count=int(row[5]),
        )
        for row in rows[:MAX_MAP_ITEMS]
    ]
    return MapResponse(mode="clusters", clusters=clusters, truncated=len(rows) > MAX_MAP_ITEMS)


async def place_detail(session: AsyncSession, place_id: int) -> PlaceDetail | None:
    now = datetime.now(timezone.utc)
    query = select(
        Place.id, Place.slug, Place.name, Place.address, Place.city, Place.region,
        Place.category, func.ST_X(Place.geometry), func.ST_Y(Place.geometry),
    ).where(Place.id == place_id, Place.is_published.is_(True))
    row = (await session.execute(query)).one_or_none()
    if row is None:
        return None
    cameras = (
        await session.execute(
            select(Camera, Source)
            .join(Source, Source.id == Camera.source_id)
            .where(
                Camera.place_id == place_id,
                Camera.is_published.is_(True),
                or_(Camera.valid_until.is_(None), Camera.valid_until > now),
                approved_source(now),
            )
            .order_by(Camera.id)
        )
    ).all()
    if not cameras:
        return None
    public_cameras = []
    for camera, source in cameras:
        can_play = (
            camera.status == "online"
            and camera.playback_type in ("hls", "iframe")
            and source.secret_ref is None
            and bool(source.stream_url and source.stream_url.startswith("https://"))
            and "?" not in source.stream_url
        )
        public_cameras.append(
            PublicCamera(
                id=camera.id,
                name=camera.name,
                playback_type=camera.playback_type,
                status=camera.status,
                last_checked_at=camera.last_checked_at,
                source_name=source.owner_name,
                source_page_url=source.public_page_url,
                attribution=source.attribution,
                playback_url=source.stream_url if can_play else None,
            )
        )
    return PlaceDetail(
        id=row[0], slug=row[1], name=row[2], address=row[3], city=row[4],
        region=row[5], category=row[6], coordinates=(float(row[7]), float(row[8])),
        cameras=public_cameras,
    )


async def search_places(session: AsyncSession, term: str, limit: int) -> SearchResponse:
    now = datetime.now(timezone.utc)
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    count = available_count(now)
    query = (
        select(
            Place.id, Place.name, Place.address, Place.city, Place.region,
            func.ST_X(Place.geometry), func.ST_Y(Place.geometry),
        )
        .where(
            Place.is_published.is_(True), count > 0,
            or_(
                Place.name.ilike(pattern, escape="\\"),
                Place.city.ilike(pattern, escape="\\"),
                Place.region.ilike(pattern, escape="\\"),
                Place.address.ilike(pattern, escape="\\"),
            ),
        )
        .order_by(Place.city, Place.name)
        .limit(limit * 4)
    )
    suggestions: list[SearchSuggestion] = []
    seen_cities: set[tuple[str, str]] = set()
    for row in (await session.execute(query)).all():
        coordinates = (float(row[5]), float(row[6]))
        if term.casefold() in row[3].casefold() and (row[3], row[4]) not in seen_cities:
            suggestions.append(SearchSuggestion(kind="city", label=f"{row[3]}, {row[4]}", coordinates=coordinates))
            seen_cities.add((row[3], row[4]))
        if row[2] and term.casefold() in row[2].casefold():
            suggestions.append(SearchSuggestion(kind="address", label=f"{row[2]}, {row[3]}", coordinates=coordinates, place_id=row[0]))
        suggestions.append(SearchSuggestion(kind="place", label=f"{row[1]}, {row[3]}", coordinates=coordinates, place_id=row[0]))
        if len(suggestions) >= limit:
            break
    return SearchResponse(suggestions=suggestions[:limit])
