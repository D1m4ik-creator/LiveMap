from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from livemap.api.errors import APIError, ErrorResponse
from livemap.api.schemas.admin import (
    AuditOutput,
    CameraAdminOutput,
    CameraInput,
    CameraPatch,
    PlaceAdminOutput,
    PlaceInput,
    PlacePatch,
    SourceAdminOutput,
    SourceInput,
    SourcePatch,
)
from livemap.core.engine import SessionDep
from livemap.db.models import AdminUser, AuditEvent, Camera, Place, Source
from livemap.services.auth import current_user, require_admin
from livemap.services.catalog_admin import (
    audit,
    commit_or_conflict,
    ensure_camera_source_type,
    ensure_place_publishable,
    place_output,
    point,
    require_camera,
    require_place,
    require_source,
)
from livemap.services.source_rules import ensure_camera_publishable, validate_source_metadata


router = APIRouter(
    prefix="/admin", tags=["admin-catalog"],
    responses={
        400: {"model": ErrorResponse}, 401: {"model": ErrorResponse},
        403: {"model": ErrorResponse}, 404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)


def admin_only(user: AdminUser) -> None:
    if user.role != "admin":
        raise APIError("forbidden", "Administrator role required", 403)


def source_output(source: Source) -> SourceAdminOutput:
    return SourceAdminOutput.model_validate(source)


def camera_output(camera: Camera) -> CameraAdminOutput:
    return CameraAdminOutput.model_validate(camera)


@router.get("/places", response_model=list[PlaceAdminOutput])
async def list_places(
    session: SessionDep,
    _actor: AdminUser = Depends(current_user),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[PlaceAdminOutput]:
    places = (await session.execute(select(Place).order_by(Place.id).limit(limit).offset(offset))).scalars()
    return [await place_output(session, place) for place in places]


@router.post("/places", response_model=PlaceAdminOutput, status_code=201)
async def create_place(body: PlaceInput, session: SessionDep, actor: AdminUser = Depends(current_user)) -> PlaceAdminOutput:
    data = body.model_dump(exclude={"coordinates"})
    place = Place(**data, geometry=point(*body.coordinates), is_published=False)
    session.add(place)
    try:
        await session.flush()
        audit(session, actor, "create", "place", place.id, f"Created draft place {place.slug}")
        await commit_or_conflict(session)
    except IntegrityError as exc:
        await session.rollback()
        raise APIError("duplicate_slug", "Place slug already exists", 409) from exc
    await session.refresh(place)
    return await place_output(session, place)


@router.get("/places/{place_id}", response_model=PlaceAdminOutput)
async def get_admin_place(place_id: int, session: SessionDep, _actor: AdminUser = Depends(current_user)) -> PlaceAdminOutput:
    return await place_output(session, await require_place(session, place_id))


@router.patch("/places/{place_id}", response_model=PlaceAdminOutput)
async def update_place(place_id: int, body: PlacePatch, session: SessionDep, actor: AdminUser = Depends(current_user)) -> PlaceAdminOutput:
    place = await require_place(session, place_id)
    if place.is_published and actor.role != "admin":
        raise APIError("forbidden", "Only administrators can change published places", 403)
    data = body.model_dump(exclude_unset=True)
    if "is_published" in data:
        admin_only(actor)
    coordinates = data.pop("coordinates", None)
    if "coordinates" in body.model_fields_set and coordinates is None:
        raise APIError("invalid_coordinates", "Coordinates cannot be null", 400)
    if coordinates is not None:
        place.geometry = point(*coordinates)
    publish = data.pop("is_published", None)
    if "is_published" in body.model_fields_set and publish is None:
        raise APIError("invalid_field", "is_published cannot be null", 400)
    for key, value in data.items():
        if value is None and key not in ("address",):
            raise APIError("invalid_field", f"{key} cannot be null", 400)
        setattr(place, key, value)
    if publish:
        await ensure_place_publishable(session, place)
    if publish is not None:
        place.is_published = publish
    audit(session, actor, "update", "place", place.id, f"Updated place {place.slug}")
    await commit_or_conflict(session)
    await session.refresh(place)
    return await place_output(session, place)


@router.delete("/places/{place_id}", status_code=204)
async def delete_place(place_id: int, session: SessionDep, actor: AdminUser = Depends(require_admin)) -> None:
    place = await require_place(session, place_id)
    audit(session, actor, "delete", "place", place.id, f"Deleted place {place.slug}")
    await session.delete(place)
    await commit_or_conflict(session)


@router.get("/sources", response_model=list[SourceAdminOutput])
async def list_sources(
    session: SessionDep, _actor: AdminUser = Depends(current_user),
    limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
) -> list[SourceAdminOutput]:
    sources = (await session.execute(select(Source).order_by(Source.id).limit(limit).offset(offset))).scalars()
    return [source_output(source) for source in sources]


@router.post("/sources", response_model=SourceAdminOutput, status_code=201)
async def create_source(body: SourceInput, session: SessionDep, actor: AdminUser = Depends(current_user)) -> SourceAdminOutput:
    source = Source(**body.model_dump(), is_approved=False)
    validate_source_metadata(source)
    session.add(source)
    await session.flush()
    audit(session, actor, "create", "source", source.id, f"Created draft source for {source.owner_name}")
    await commit_or_conflict(session)
    await session.refresh(source)
    return source_output(source)


@router.get("/sources/{source_id}", response_model=SourceAdminOutput)
async def get_admin_source(source_id: int, session: SessionDep, _actor: AdminUser = Depends(current_user)) -> SourceAdminOutput:
    return source_output(await require_source(session, source_id))


@router.patch("/sources/{source_id}", response_model=SourceAdminOutput)
async def update_source(source_id: int, body: SourcePatch, session: SessionDep, actor: AdminUser = Depends(current_user)) -> SourceAdminOutput:
    source = await require_source(session, source_id)
    if source.is_approved and actor.role != "admin":
        raise APIError("forbidden", "Only administrators can change approved sources", 403)
    data = body.model_dump(exclude_unset=True)
    approved = data.pop("is_approved", None)
    if "is_approved" in body.model_fields_set and approved is None:
        raise APIError("invalid_field", "is_approved cannot be null", 400)
    if "is_approved" in body.model_fields_set:
        admin_only(actor)
    for key, value in data.items():
        if value is None and key in ("owner_name", "public_page_url", "attribution", "permission_note"):
            raise APIError("invalid_field", f"{key} cannot be null", 400)
        setattr(source, key, value)
    validate_source_metadata(source)
    reset_approval = any(key in data for key in (
        "owner_name", "public_page_url", "stream_url", "secret_ref", "attribution",
        "permission_note", "permission_evidence_url", "permission_reviewed_at",
        "embed_host", "permission_expires_at", "removal_contact",
    ))
    if approved is True and reset_approval:
        raise APIError("review_required", "Review changed source in a separate request before approval", 409)
    if reset_approval:
        source.is_approved = False
        linked_cameras = (await session.execute(
            select(Camera).where(Camera.source_id == source.id)
        )).scalars()
        for camera in linked_cameras:
            camera.is_published = False
            camera.status = "unknown"
            camera.last_checked_at = None
            camera.embed_verified_at = None
            camera.unpublished_reason = "source_changed"
            audit(session, actor, "unpublish", "camera", camera.id, f"Camera {camera.id} unpublished after source change")
    if approved is True:
        if not source.stream_url:
            raise APIError("missing_stream", "Заполните URL потока или iframe и сохраните источник перед одобрением.", 409)
        if source.permission_expires_at and source.permission_expires_at <= datetime.now(timezone.utc):
            raise APIError("permission_expired", "Срок разрешения источника истёк. Проверьте поле «Срок разрешения» и сохраните действующие условия перед одобрением.", 409)
        if not source.permission_evidence_url or not source.permission_reviewed_at or not source.removal_contact:
            raise APIError("rights_incomplete", "Permission evidence, review date and removal contact are required", 409)
        linked_cameras = (
            await session.execute(select(Camera).where(Camera.source_id == source.id))
        ).scalars()
        for camera in linked_cameras:
            try:
                ensure_camera_source_type(camera.playback_type, source)
            except APIError as exc:
                raise APIError("incompatible_source", "Source URL conflicts with linked camera type", 409) from exc
    if approved is not None:
        source.is_approved = approved
        if approved is False and not reset_approval:
            linked_cameras = (await session.execute(
                select(Camera).where(Camera.source_id == source.id)
            )).scalars()
            for camera in linked_cameras:
                camera.is_published = False
                camera.status = "unknown"
                camera.unpublished_reason = "permission_revoked"
                audit(session, actor, "unpublish", "camera", camera.id, f"Camera {camera.id} unpublished after permission revocation")
    audit(session, actor, "update", "source", source.id, f"Updated source {source.id}; approved={source.is_approved}")
    await commit_or_conflict(session)
    await session.refresh(source)
    return source_output(source)


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(source_id: int, session: SessionDep, actor: AdminUser = Depends(require_admin)) -> None:
    source = await require_source(session, source_id)
    audit(session, actor, "delete", "source", source.id, f"Deleted source {source.id}")
    await session.delete(source)
    await commit_or_conflict(session)


@router.get("/cameras", response_model=list[CameraAdminOutput])
async def list_cameras(
    session: SessionDep, _actor: AdminUser = Depends(current_user),
    limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
) -> list[CameraAdminOutput]:
    cameras = (await session.execute(select(Camera).order_by(Camera.id).limit(limit).offset(offset))).scalars()
    return [camera_output(camera) for camera in cameras]


@router.post("/cameras", response_model=CameraAdminOutput, status_code=201)
async def create_camera(body: CameraInput, session: SessionDep, actor: AdminUser = Depends(current_user)) -> CameraAdminOutput:
    await require_place(session, body.place_id)
    source = await require_source(session, body.source_id)
    ensure_camera_source_type(body.playback_type, source)
    camera = Camera(**body.model_dump(), is_published=False, status="unknown")
    session.add(camera)
    await session.flush()
    audit(session, actor, "create", "camera", camera.id, f"Created draft camera {camera.name}")
    await commit_or_conflict(session)
    await session.refresh(camera)
    return camera_output(camera)


@router.get("/cameras/{camera_id}", response_model=CameraAdminOutput)
async def get_admin_camera(camera_id: int, session: SessionDep, _actor: AdminUser = Depends(current_user)) -> CameraAdminOutput:
    return camera_output(await require_camera(session, camera_id))


@router.patch("/cameras/{camera_id}", response_model=CameraAdminOutput)
async def update_camera(camera_id: int, body: CameraPatch, session: SessionDep, actor: AdminUser = Depends(current_user)) -> CameraAdminOutput:
    camera = await require_camera(session, camera_id)
    if camera.is_published and actor.role != "admin":
        raise APIError("forbidden", "Only administrators can change published cameras", 403)
    data = body.model_dump(exclude_unset=True)
    if "is_published" in data or "status" in data:
        admin_only(actor)
    publication = data.pop("is_published", None)
    status = data.pop("status", None)
    if "is_published" in body.model_fields_set and publication is None:
        raise APIError("invalid_field", "is_published cannot be null", 400)
    if "status" in body.model_fields_set and status is None:
        raise APIError("invalid_field", "status cannot be null", 400)
    for key, value in data.items():
        if value is None and key not in ("valid_until", "embed_verified_at"):
            raise APIError("invalid_field", f"{key} cannot be null", 400)
        setattr(camera, key, value)
    await require_place(session, camera.place_id)
    source = await require_source(session, camera.source_id)
    ensure_camera_source_type(camera.playback_type, source)
    if any(key in data for key in ("source_id", "playback_type")):
        camera.is_published = False
        camera.status = "unknown"
        camera.embed_verified_at = None
    if publication:
        ensure_camera_publishable(camera, source)
    if publication is not None:
        camera.is_published = publication
    if status is not None:
        camera.status = status
        camera.last_checked_at = datetime.now(timezone.utc)
    audit(session, actor, "update", "camera", camera.id, f"Updated camera {camera.id}; published={camera.is_published}")
    await commit_or_conflict(session)
    await session.refresh(camera)
    return camera_output(camera)


@router.delete("/cameras/{camera_id}", status_code=204)
async def delete_camera(camera_id: int, session: SessionDep, actor: AdminUser = Depends(require_admin)) -> None:
    camera = await require_camera(session, camera_id)
    audit(session, actor, "delete", "camera", camera.id, f"Deleted camera {camera.id}")
    await session.delete(camera)
    await commit_or_conflict(session)


@router.get("/audit", response_model=list[AuditOutput])
async def list_audit(
    session: SessionDep, _actor: AdminUser = Depends(require_admin),
    limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
) -> list[AuditEvent]:
    return list((await session.execute(
        select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit).offset(offset)
    )).scalars())
