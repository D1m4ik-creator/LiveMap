from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from livemap.api.errors import register_error_handlers
from livemap.api.routers.admin_auth import router as admin_auth_router
from livemap.api.routers.admin_catalog import router as admin_catalog_router
from livemap.api.routers.admin_import import router as admin_import_router
from livemap.api.routers.health import router as health_router
from livemap.api.routers.places import router as places_router
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
    app.include_router(places_router, prefix="/api/v1")
    app.include_router(admin_auth_router, prefix="/api/v1")
    app.include_router(admin_catalog_router, prefix="/api/v1")
    app.include_router(admin_import_router, prefix="/api/v1")
    return app


app = create_app()
