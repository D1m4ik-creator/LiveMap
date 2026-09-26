from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReportInput(BaseModel):
    reason: Literal["rights", "privacy", "terms", "broken", "other"]
    details: str = Field(min_length=10, max_length=2000)
    contact: str | None = Field(default=None, max_length=255)


class ReportOutput(ReportInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    camera_id: int
    status: Literal["open", "resolved"]
    resolution: str | None
    created_at: datetime
    resolved_at: datetime | None


class ResolveReportInput(BaseModel):
    resolution: str = Field(min_length=10, max_length=2000)
    unpublish_camera: bool = False


class CameraCheckOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    camera_id: int
    checked_at: datetime
    result: Literal["online", "offline", "unknown"]
    code: str
    duration_ms: int
