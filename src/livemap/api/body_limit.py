"""Bound request bytes before FastAPI buffers or parses an unauthenticated body."""

import asyncio
import time

from starlette.responses import JSONResponse


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        limit = 8_100_000 if path.startswith("/api/v1/admin/import/") else 64_000
        if path == "/api/v1/admin/login":
            limit = 16_000

        async def reject(status, code, message):
            await JSONResponse({"error": {"code": code, "message": message}}, status_code=status)(scope, receive, send)

        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    length = int(value)
                    if length < 0:
                        raise ValueError()
                except ValueError:
                    return await reject(400, "invalid_length", "Invalid Content-Length")
                if length > limit:
                    return await reject(413, "body_too_large", "Request body is too large")
        # Check chunked requests too; the downstream parser sees only a bounded body.
        body = bytearray()
        deadline = time.monotonic() + 30
        while True:
            try:
                message = await asyncio.wait_for(receive(), timeout=max(0.001, deadline - time.monotonic()))
            except TimeoutError:
                return await reject(408, "body_timeout", "Request body timed out")
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > limit:
                return await reject(413, "body_too_large", "Request body is too large")
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
