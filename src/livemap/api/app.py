from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import asyncio
import json
import logging
import time
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from livemap.api.errors import register_error_handlers
from livemap.api.routers.admin_auth import router as admin_auth_router
from livemap.api.routers.admin_catalog import router as admin_catalog_router
from livemap.api.routers.admin_import import router as admin_import_router
from livemap.api.routers.health import router as health_router
from livemap.api.routers.monitoring import admin_router as monitoring_admin_router, public_router as monitoring_public_router
from livemap.api.routers.places import router as places_router
from livemap.core.config import ROOT_DIR, get_settings
from livemap.core.engine import close_engine, get_engine

logger = logging.getLogger("livemap.requests")
REQUESTS = Counter("livemap_http_requests_total", "HTTP requests", ("method", "route", "status"))
LATENCY = Histogram("livemap_http_duration_seconds", "HTTP request duration", ("method", "route"))


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    get_engine()
    worker_task = None
    if settings.embedded_worker:
        from livemap.worker import run_once

        async def check_loop() -> None:
            while True:
                try:
                    await run_once()
                except Exception:
                    logger.exception("embedded camera worker failed")
                await asyncio.sleep(10)

        worker_task = asyncio.create_task(check_loop())
    try:
        yield
    finally:
        if worker_task is not None:
            worker_task.cancel()
            await asyncio.gather(worker_task, return_exceptions=True)
        await close_engine()


def create_app() -> FastAPI:
    serve_frontend = get_settings().serve_frontend
    frontend_dir = ROOT_DIR / "frontend-dist"
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
            if serve_frontend and request.url.path.startswith("/internal/"):
                response = Response(status_code=404)
            else:
                response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            if serve_frontend:
                response.headers["X-Content-Type-Options"] = "nosniff"
                response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
                response.headers["X-Frame-Options"] = "DENY"
                response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(self)"
                response.headers["Content-Security-Policy"] = (
                    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' "
                    "https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:; "
                    "img-src 'self' data: blob: https:; connect-src 'self' https:; "
                    "media-src 'self' blob: https:; frame-src https://ipeye.ru "
                    "https://open.ivideon.com https://rutube.ru; worker-src 'self' blob:; "
                    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
                )
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
    if serve_frontend:
        @app.get("/{full_path:path}", include_in_schema=False)
        async def frontend(full_path: str) -> FileResponse:
            if full_path in {"api", "internal"} or full_path.startswith(("api/", "internal/")):
                raise HTTPException(status_code=404)
            requested = (frontend_dir / full_path).resolve()
            if requested.is_relative_to(frontend_dir.resolve()) and requested.is_file():
                return FileResponse(requested)
            if full_path.startswith("assets/") or "." in Path(full_path).name:
                raise HTTPException(status_code=404)
            return FileResponse(frontend_dir / "index.html")

    return app


app = create_app()
