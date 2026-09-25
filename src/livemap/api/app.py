from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from livemap.api.errors import register_error_handlers
from livemap.api.routers.health import router as health_router
from livemap.core.config import get_settings
from livemap.core.engine import close_engine, get_engine


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    get_settings()
    get_engine()
    yield
    await close_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="LiveMap API",
        description="Metadata API for public live camera locations.",
        version="0.1.0",
        lifespan=lifespan,
    )
    register_error_handlers(app)
    app.include_router(health_router, prefix="/api/v1")
    return app


app = create_app()
