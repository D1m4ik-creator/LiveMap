import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select, text

from livemap.api.errors import APIError, ErrorResponse
from livemap.core.engine import get_engine
from livemap.core.engine import SessionDep
from livemap.db.models import Camera, Source
from livemap.repositories.catalog import available_camera, published_camera

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


class CameraHealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    published: int
    online: int
    stale: int
    latest_check_at: datetime | None


@router.get("/cameras", response_model=CameraHealthResponse)
async def camera_health(session: SessionDep) -> CameraHealthResponse:
    """Public aggregate only: no source URLs, reports or admin identities."""
    now = datetime.now(timezone.utc)
    result = (await session.execute(
        select(
            func.count(Camera.id),
            func.count(Camera.id).filter(available_camera(now)),
            func.count(Camera.id).filter(
                Camera.last_checked_at.is_(None) | (Camera.last_checked_at < now - timedelta(minutes=15))
            ),
            func.max(Camera.last_checked_at),
        ).join(Source).where(published_camera(now))
    )).one()
    published, online, stale, latest = result
    return CameraHealthResponse(
        status="ok" if published and online and not stale else "degraded",
        published=published, online=online, stale=stale, latest_check_at=latest,
    )


async def check_database() -> None:
    async with get_engine().connect() as connection:
        await connection.execute(text("SELECT 1"))


@router.get("/live", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/ready",
    response_model=HealthResponse,
    responses={503: {"model": ErrorResponse}},
)
async def readiness() -> HealthResponse:
    try:
        await asyncio.wait_for(check_database(), timeout=3.0)
    except Exception as exc:
        logger.warning("Database readiness check failed: %s", type(exc).__name__)
        raise APIError(
            code="database_unavailable",
            message="Database is unavailable",
            status_code=503,
        ) from exc
    return HealthResponse(status="ok")
