from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class MapPoint(BaseModel):
    id: int
    slug: str
    name: str
    city: str
    category: str
    coordinates: tuple[float, float]
    camera_count: int
    online_count: int
    status: Literal["online", "offline"]


class MapCluster(BaseModel):
    id: str
    coordinates: tuple[float, float]
    place_count: int
    camera_count: int
    online_count: int
    status: Literal["online", "offline"]


class MapResponse(BaseModel):
    mode: Literal["points", "clusters"]
    points: list[MapPoint] = Field(default_factory=list)
    clusters: list[MapCluster] = Field(default_factory=list)
    truncated: bool = False


class PublicCamera(BaseModel):
    id: int
    name: str
    playback_type: Literal["hls", "iframe", "rtsp"]
    status: Literal["online", "offline", "unknown"]
    last_checked_at: datetime | None
    last_success_at: datetime | None
    availability_note: str | None
    source_name: str
    source_page_url: str
    attribution: str
    playback_url: str | None
    embed_host: str | None


class PlaceDetail(BaseModel):
    id: int
    slug: str
    name: str
    address: str | None
    city: str
    region: str
    category: str
    coordinates: tuple[float, float]
    cameras: list[PublicCamera]


class SearchSuggestion(BaseModel):
    kind: Literal["city", "address", "place"]
    label: str
    coordinates: tuple[float, float]
    place_id: int | None = None


class SearchResponse(BaseModel):
    suggestions: list[SearchSuggestion]
