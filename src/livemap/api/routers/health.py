import asyncio
import logging
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from livemap.api.errors import APIError, ErrorResponse
from livemap.core.engine import get_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


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
