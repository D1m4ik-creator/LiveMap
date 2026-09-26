from typing import Literal

from pydantic import BaseModel, Field


class ImportInput(BaseModel):
    format: Literal["csv", "geojson"]
    content: str = Field(min_length=1, max_length=2_000_000)


class ImportItem(BaseModel):
    row: int
    slug: str
    action: Literal["create", "update"]
    has_camera: bool


class ImportError(BaseModel):
    row: int
    message: str


class ImportPreview(BaseModel):
    items: list[ImportItem]
    errors: list[ImportError]


class ImportResult(BaseModel):
    created: int
    updated: int
    draft_cameras: int
