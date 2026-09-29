from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from livemap.api.errors import register_error_handlers
from livemap.api.routers.admin_auth import router as admin_auth_router
from livemap.api.routers.admin_catalog import router as admin_catalog_router
from livemap.api.routers.admin_import import router as admin_import_router
from livemap.api.routers.health import router as health_router
from livemap.api.routers.monitoring import admin_router as monitoring_admin_router, public_router as monitoring_public_router
from livemap.api.routers.places import router as places_router
from livemap.core.config import get_settings
from livemap.core.engine import close_engine, get_engine

logger = logging.getLogger("livemap.requests")
REQUESTS = Counter("livemap_http_requests_total", "HTTP requests", ("method", "route", "status"))
LATENCY = Histogram("livemap_http_duration_seconds", "HTTP request duration", ("method", "route"))


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

    @app.middleware("http")
    async def observe(request: Request, call_next):
        start = time.monotonic()
        request_id = uuid4().hex
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            route = request.scope.get("route")
            label = route.path if route is not None else "unmatched"
            duration = time.monotonic() - start
            REQUESTS.labels(request.method, label, str(status)).inc()
            LATENCY.labels(request.method, label).observe(duration)
            logger.info(json.dumps({"event": "http_request", "request_id": request_id,
                                    "method": request.method, "route": label, "status": status,
                                    "duration_ms": round(duration * 1000, 1)}))

    @app.get("/internal/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(places_router, prefix="/api/v1")
    app.include_router(admin_auth_router, prefix="/api/v1")
    app.include_router(admin_catalog_router, prefix="/api/v1")
    app.include_router(admin_import_router, prefix="/api/v1")
    app.include_router(monitoring_public_router, prefix="/api/v1")
    app.include_router(monitoring_admin_router, prefix="/api/v1")
    return app


app = create_app()
