from fastapi import APIRouter, Query, Request

from livemap.api.errors import APIError, ErrorResponse
from livemap.api.schemas.catalog import MapResponse, PlaceDetail, SearchResponse
from livemap.core.engine import SessionDep
from livemap.repositories.catalog import map_items, place_detail, search_places
from livemap.services.geo import parse_bbox
from livemap.services.rate_limit import search_limiter


router = APIRouter(
    prefix="/places", tags=["places"],
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)


@router.get("", response_model=MapResponse, responses={400: {"model": ErrorResponse}})
async def get_map_places(
    session: SessionDep,
    bbox: str = Query(description="west,south,east,north in WGS84"),
    zoom: int = Query(ge=0, le=20),
    category: str | None = Query(default=None, min_length=2, max_length=80),
    include_offline: bool = Query(default=False),
) -> MapResponse:
    return await map_items(session, parse_bbox(bbox, zoom), zoom, category, include_offline)


@router.get("/search", response_model=SearchResponse, responses={429: {"model": ErrorResponse}})
async def search(
    request: Request,
    session: SessionDep,
    q: str = Query(min_length=2, max_length=80),
    limit: int = Query(default=10, ge=1, le=20),
    include_offline: bool = Query(default=False),
) -> SearchResponse:
    q = q.strip()
    if len(q) < 2:
        raise APIError("invalid_search", "Search term must contain at least two characters", 400)
    await search_limiter.check(request.client.host if request.client else "unknown")
    return await search_places(session, q, limit, include_offline)


@router.get("/{place_id}", response_model=PlaceDetail, responses={404: {"model": ErrorResponse}})
async def get_place(place_id: int, session: SessionDep) -> PlaceDetail:
    detail = await place_detail(session, place_id)
    if detail is None:
        raise APIError("place_not_found", "Place not found", 404)
    return detail
