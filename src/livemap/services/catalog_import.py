import csv
import io
import json
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from livemap.api.errors import APIError
from livemap.api.schemas.admin import PlaceInput, SourceInput
from livemap.api.schemas.imports import ImportError, ImportInput, ImportItem, ImportPreview, ImportResult
from livemap.db.models import AdminUser, Camera, Place, Source
from livemap.services.catalog_admin import audit, commit_or_conflict, point
from livemap.services.source_rules import validate_source_urls, validate_url


MAX_IMPORT_ROWS = 1000
PLACE_FIELDS = {"slug", "name", "address", "city", "region", "category", "coordinates"}
SOURCE_FIELDS = {
    "owner_name", "public_page_url", "stream_url", "secret_ref", "attribution",
    "permission_note", "permission_expires_at", "removal_contact",
}


@dataclass
class ParsedRow:
    number: int
    place: PlaceInput
    source: SourceInput | None
    camera_name: str | None
    playback_type: str | None


def raw_rows(body: ImportInput) -> list[dict[str, Any]]:
    if body.format == "csv":
        try:
            reader = csv.DictReader(io.StringIO(body.content.lstrip("\ufeff"), newline=""))
            if not reader.fieldnames or not {"slug", "name", "city", "region", "category", "longitude", "latitude"} <= set(reader.fieldnames):
                raise APIError("invalid_import", "CSV is missing required place columns", 400)
            rows = list(reader)
        except csv.Error as exc:
            raise APIError("invalid_import", "CSV could not be read", 400) from exc
    else:
        try:
            document = json.loads(body.content.lstrip("\ufeff"))
        except json.JSONDecodeError as exc:
            raise APIError("invalid_import", "GeoJSON is invalid", 400) from exc
        if not isinstance(document, dict) or document.get("type") != "FeatureCollection" or not isinstance(document.get("features"), list):
            raise APIError("invalid_import", "GeoJSON must be a FeatureCollection", 400)
        rows = []
        for feature in document["features"]:
            if not isinstance(feature, dict) or not isinstance(feature.get("properties"), dict):
                rows.append({"_error": "Feature must have properties"})
                continue
            geometry = feature.get("geometry")
            if not isinstance(geometry, dict) or geometry.get("type") != "Point" or not isinstance(geometry.get("coordinates"), list) or len(geometry["coordinates"]) != 2:
                rows.append({"_error": "Feature geometry must be a Point [longitude, latitude]"})
                continue
            rows.append({**feature["properties"], "longitude": geometry["coordinates"][0], "latitude": geometry["coordinates"][1]})
    if len(rows) > MAX_IMPORT_ROWS:
        raise APIError("import_too_large", "Import exceeds 1000 rows", 400)
    return rows


def parse_row(number: int, raw: dict[str, Any]) -> ParsedRow:
    if "_error" in raw:
        raise ValueError(raw["_error"])
    place_data = {key: raw.get(key) for key in PLACE_FIELDS if key != "coordinates"}
    place_data["coordinates"] = (raw.get("longitude"), raw.get("latitude"))
    place = PlaceInput.model_validate(place_data)
    camera_name = raw.get("camera_name") or None
    if not camera_name:
        return ParsedRow(number, place, None, None, None)
    if len(str(camera_name)) < 2 or len(str(camera_name)) > 255:
        raise ValueError("camera_name must contain 2-255 characters")
    playback_type = raw.get("playback_type")
    if playback_type not in ("hls", "iframe", "rtsp"):
        raise ValueError("playback_type must be hls, iframe or rtsp")
    source = SourceInput.model_validate({key: raw.get(key) for key in SOURCE_FIELDS})
    validate_source_urls(source.public_page_url, source.stream_url)
    if source.stream_url:
        validate_url(source.stream_url, {"rtsp"} if playback_type == "rtsp" else {"https"})
    return ParsedRow(number, place, source, str(camera_name), playback_type)


async def prepare_import(session: AsyncSession, body: ImportInput) -> tuple[ImportPreview, list[ParsedRow]]:
    parsed: list[ParsedRow] = []
    errors: list[ImportError] = []
    seen: dict[str, tuple[PlaceInput, set[tuple[str, str, str | None]]]] = {}
    for number, raw in enumerate(raw_rows(body), start=1):
        try:
            item = parse_row(number, raw)
            if item.place.slug in seen:
                previous_place, camera_keys = seen[item.place.slug]
                if item.place != previous_place:
                    raise ValueError("Repeated slug has conflicting place fields")
                if item.source is None:
                    raise ValueError("Duplicate place without another camera")
                key = (item.camera_name, item.source.public_page_url, item.source.stream_url)
                if key in camera_keys:
                    raise ValueError("Duplicate camera in import file")
                camera_keys.add(key)
            else:
                keys = set()
                if item.source is not None:
                    keys.add((item.camera_name, item.source.public_page_url, item.source.stream_url))
                seen[item.place.slug] = (item.place, keys)
            parsed.append(item)
        except (ValidationError, ValueError, APIError) as exc:
            errors.append(ImportError(row=number, message=str(exc)))
    existing: set[str] = set()
    if parsed:
        existing = set((await session.execute(
            select(Place.slug).where(Place.slug.in_([item.place.slug for item in parsed]))
        )).scalars())
    items = []
    preview_seen = set(existing)
    for item in parsed:
        items.append(ImportItem(
            row=item.number, slug=item.place.slug,
            action="update" if item.place.slug in preview_seen else "create",
            has_camera=item.source is not None,
        ))
        preview_seen.add(item.place.slug)
    return ImportPreview(items=items, errors=errors), parsed


async def apply_import(session: AsyncSession, body: ImportInput, actor: AdminUser) -> ImportResult:
    preview, parsed = await prepare_import(session, body)
    if preview.errors:
        raise APIError("import_has_errors", "Fix all preview errors before importing", 400)
    created = updated = draft_cameras = 0
    for item in parsed:
        data = item.place.model_dump(exclude={"coordinates"})
        place = (await session.execute(select(Place).where(Place.slug == item.place.slug))).scalar_one_or_none()
        if place is None:
            place = Place(**data, geometry=point(*item.place.coordinates), is_published=False)
            session.add(place)
            await session.flush()
            created += 1
        else:
            changed = False
            for key, value in data.items():
                if getattr(place, key) != value:
                    setattr(place, key, value)
                    changed = True
            current = (
                await session.execute(
                    select(
                        func.ST_X(Place.geometry),
                        func.ST_Y(Place.geometry),
                    ).where(Place.id == place.id)
                )
            ).one()
            if (float(current[0]), float(current[1])) != item.place.coordinates:
                place.geometry = point(*item.place.coordinates)
                changed = True
            if changed:
                place.is_published = False
            updated += 1
        if item.source is None:
            continue
        source_data = item.source.model_dump()
        source = (
            await session.execute(
                select(Source).where(
                    Source.owner_name == item.source.owner_name,
                    Source.public_page_url == item.source.public_page_url,
                    Source.stream_url == item.source.stream_url,
                )
            )
        ).scalar_one_or_none()
        if source is None:
            source = Source(**source_data, is_approved=False)
            session.add(source)
            await session.flush()
        else:
            changed = False
            for key, value in source_data.items():
                if getattr(source, key) != value:
                    setattr(source, key, value)
                    changed = True
            if changed:
                source.is_approved = False
        camera = (
            await session.execute(
                select(Camera).where(
                    Camera.place_id == place.id,
                    Camera.source_id == source.id,
                    Camera.name == item.camera_name,
                )
            )
        ).scalar_one_or_none()
        if camera is None:
            camera = Camera(
                place_id=place.id, source_id=source.id, name=item.camera_name,
                playback_type=item.playback_type, status="unknown", is_published=False,
            )
            session.add(camera)
        else:
            if camera.playback_type != item.playback_type:
                camera.playback_type = item.playback_type
                camera.status = "unknown"
                camera.is_published = False
        draft_cameras += 1
    audit(session, actor, "import", "catalog", None, f"Imported {created} new and {updated} updated draft places")
    await commit_or_conflict(session)
    return ImportResult(created=created, updated=updated, draft_cameras=draft_cameras)
