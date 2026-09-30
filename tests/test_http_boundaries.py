import asyncio

import httpx

from livemap.api.app import app
from livemap.api.body_limit import BodyLimitMiddleware
from livemap.services.rate_limit import RequestRateLimiter
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware


def test_oversized_requests_rejected_before_json_and_auth() -> None:
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/admin/login", content=b"invalid" * 3000)
            assert response.status_code == 413
            assert response.json()["error"]["code"] == "body_too_large"
            async def chunks():
                for _ in range(3):
                    yield b"x" * 6000
            response = await client.post("/api/v1/admin/login", content=chunks())
            assert response.status_code == 413
            response = await client.post("/api/v1/admin/import/preview", headers={"Content-Length": "8100001"})
            assert response.status_code == 413
    asyncio.run(run())


def test_bounded_body_is_delivered_and_untrusted_forwarding_ignored() -> None:
    async def run():
        limiter = RequestRateLimiter(1, 60, "limit", "limit")
        seen = []
        async def inner(scope, receive, send):
            message = await receive()
            seen.append((scope["client"][0], message["body"]))
            await limiter.check(scope["client"][0])
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})
        trusted = ProxyHeadersMiddleware(BodyLimitMiddleware(inner), trusted_hosts="172.20.0.0/16")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=trusted, client=("172.20.0.4", 1000)), base_url="http://test") as client:
            for address in ("203.0.113.1", "203.0.113.2"):
                assert (await client.post("/", headers={"X-Forwarded-For": address}, content=b"valid")).status_code == 200
        assert seen == [("203.0.113.1", b"valid"), ("203.0.113.2", b"valid")]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=trusted, client=("198.51.100.10", 1000)), base_url="http://test") as client:
            assert (await client.post("/", headers={"X-Forwarded-For": "203.0.113.3"})).status_code == 200
        assert seen[-1][0] == "198.51.100.10"
    asyncio.run(run())
