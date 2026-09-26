from datetime import datetime
from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)


class LoginOutput(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    role: Literal["admin", "editor"]


class AdminUserOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    role: Literal["admin", "editor"]


class CreateUserInput(BaseModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9_.-]+$", min_length=3, max_length=100)
    password: str = Field(min_length=12, max_length=1024)
    role: Literal["admin", "editor"] = "editor"


class PlaceInput(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=2, max_length=160)
    name: str = Field(min_length=2, max_length=255)
    address: str | None = Field(default=None, max_length=500)
    city: str = Field(min_length=2, max_length=160)
    region: str = Field(min_length=2, max_length=160)
    category: str = Field(min_length=2, max_length=80)
    coordinates: tuple[float, float]

    @field_validator("coordinates")
    @classmethod
    def valid_coordinates(cls, value: tuple[float, float]) -> tuple[float, float]:
        if not all(isfinite(item) for item in value) or not (-180 <= value[0] <= 180 and -90 <= value[1] <= 90):
            raise ValueError("Coordinates must be [longitude, latitude] in WGS84")
        return value


class PlacePatch(BaseModel):
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=2, max_length=160)
    name: str | None = Field(default=None, min_length=2, max_length=255)
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, min_length=2, max_length=160)
    region: str | None = Field(default=None, min_length=2, max_length=160)
    category: str | None = Field(default=None, min_length=2, max_length=80)
    coordinates: tuple[float, float] | None = None
    is_published: bool | None = None

    _valid_coordinates = field_validator("coordinates")(PlaceInput.valid_coordinates.__func__)


class PlaceAdminOutput(PlaceInput):
    id: int
    is_published: bool
    created_at: datetime
    updated_at: datetime


class SourceInput(BaseModel):
    owner_name: str = Field(min_length=2, max_length=255)
    public_page_url: str = Field(max_length=1000)
    stream_url: str | None = Field(default=None, max_length=1000)
    secret_ref: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$", max_length=160)
    attribution: str = Field(min_length=2, max_length=255)
    permission_note: str = Field(min_length=5, max_length=4000)
    permission_expires_at: datetime | None = None
    removal_contact: str | None = Field(default=None, max_length=255)

    @field_validator("permission_expires_at")
    @classmethod
    def aware_expiry(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("Expiry must include a timezone")
        return value


class SourcePatch(BaseModel):
    owner_name: str | None = Field(default=None, min_length=2, max_length=255)
    public_page_url: str | None = Field(default=None, max_length=1000)
    stream_url: str | None = Field(default=None, max_length=1000)
    secret_ref: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$", max_length=160)
    attribution: str | None = Field(default=None, min_length=2, max_length=255)
    permission_note: str | None = Field(default=None, min_length=5, max_length=4000)
    permission_expires_at: datetime | None = None
    removal_contact: str | None = Field(default=None, max_length=255)
    is_approved: bool | None = None

    _aware_expiry = field_validator("permission_expires_at")(SourceInput.aware_expiry.__func__)


class SourceAdminOutput(SourceInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_approved: bool
    created_at: datetime
    updated_at: datetime


class CameraInput(BaseModel):
    place_id: int = Field(gt=0)
    source_id: int = Field(gt=0)
    name: str = Field(min_length=2, max_length=255)
    playback_type: Literal["hls", "iframe", "rtsp"]
    valid_until: datetime | None = None

    @field_validator("valid_until")
    @classmethod
    def aware_valid_until(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("Validity time must include a timezone")
        return value


class CameraPatch(BaseModel):
    place_id: int | None = Field(default=None, gt=0)
    source_id: int | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, min_length=2, max_length=255)
    playback_type: Literal["hls", "iframe", "rtsp"] | None = None
    valid_until: datetime | None = None
    is_published: bool | None = None
    status: Literal["online", "offline", "unknown"] | None = None

    _aware_valid_until = field_validator("valid_until")(CameraInput.aware_valid_until.__func__)


class CameraAdminOutput(CameraInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_published: bool
    status: Literal["online", "offline", "unknown"]
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AuditOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    actor_id: int | None
    action: str
    entity_type: str
    entity_id: int | None
    summary: str
    created_at: datetime
