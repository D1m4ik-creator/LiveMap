"""Bounded, DNS-pinned probes for approved public camera sources.

Never use this module as a user-supplied URL fetcher. It deliberately refuses
redirects, private DNS answers, URL credentials and HTTP downgrades.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import aiohttp

from livemap.api.errors import APIError
from livemap.services.source_rules import validate_url


MAX_MANIFEST_BYTES = 256 * 1024
MAX_FRAME_BYTES = 16 * 1024


class ProbeFailure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ProbeResult:
    status: str
    code: str
    duration_ms: int


def safe_https_url(value: str) -> str:
    try:
        validate_url(value, {"https"})
    except APIError as exc:
        raise ProbeFailure("unsafe_url") from exc
    if urlsplit(value).query:
        raise ProbeFailure("signed_url_requires_gateway")
    return value


class PublicResolver(aiohttp.abc.AbstractResolver):
    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET) -> list[dict]:
        try:
            answers = await asyncio.get_running_loop().getaddrinfo(
                host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
            )
        except OSError as exc:
            raise ProbeFailure("dns_failed") from exc
        if not answers:
            raise ProbeFailure("dns_failed")
        return public_dns_answers(host, port, answers)

    async def close(self) -> None:
        return None


def public_dns_answers(host: str, port: int, answers: list[tuple]) -> list[dict]:
    result = []
    for af, _type, proto, _canonical, sockaddr in answers:
        address = ipaddress.ip_address(sockaddr[0])
        if not address.is_global:
            raise ProbeFailure("private_address")
        result.append({
            "hostname": host, "host": str(address), "port": port,
            "family": af, "proto": proto, "flags": socket.AI_NUMERICHOST,
        })
    return result


def cors_allowed(header: str | None, origin: str) -> bool:
    return header in ("*", origin)


def first_playlist_uri(manifest: str) -> str:
    if not manifest.lstrip().startswith("#EXTM3U"):
        raise ProbeFailure("invalid_manifest")
    for line in manifest.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    raise ProbeFailure("empty_manifest")


def frame_policy_allows(headers: aiohttp.typedefs.LooseHeaders, origin: str) -> bool:
    xfo = str(headers.get("X-Frame-Options", "")).upper()
    if xfo.startswith(("DENY", "SAMEORIGIN")):
        return False
    csp = str(headers.get("Content-Security-Policy", ""))
    for directive in csp.split(";"):
        tokens = directive.strip().split()
        if tokens and tokens[0].lower() == "frame-ancestors":
            return "*" in tokens[1:] or origin in tokens[1:]
    return True


class CameraProbe:
    def __init__(self, origin: str) -> None:
        self.origin = origin.rstrip("/")
        timeout = aiohttp.ClientTimeout(total=12, connect=5, sock_read=5)
        connector = aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False, limit=4)
        self.client = aiohttp.ClientSession(
            connector=connector, timeout=timeout, trust_env=False,
            headers={"Origin": self.origin, "User-Agent": "LiveMap-availability/1.0"},
        )

    async def __aenter__(self) -> CameraProbe:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.client.close()

    async def _fetch(self, url: str, limit: int, *, cors: bool, sample: bool = False) -> tuple[bytes, aiohttp.typedefs.LooseHeaders]:
        safe_https_url(url)
        try:
            async with self.client.get(url, allow_redirects=False) as response:
                if 300 <= response.status < 400:
                    raise ProbeFailure("redirect_rejected")
                if response.status not in (200, 206):
                    raise ProbeFailure("http_error")
                if cors and not cors_allowed(response.headers.get("Access-Control-Allow-Origin"), self.origin):
                    raise ProbeFailure("cors_denied")
                body = await response.content.read(limit if sample else limit + 1)
                if not sample and len(body) > limit:
                    raise ProbeFailure("response_too_large")
                return body, response.headers
        except ProbeFailure:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            raise ProbeFailure("connection_failed") from exc

    async def hls(self, url: str) -> None:
        body, _ = await self._fetch(url, MAX_MANIFEST_BYTES, cors=True)
        manifest = body.decode("utf-8-sig", errors="replace")
        first = first_playlist_uri(manifest)
        child = safe_https_url(urljoin(url, first))
        if "#EXT-X-STREAM-INF" in manifest:
            variant, _ = await self._fetch(child, MAX_MANIFEST_BYTES, cors=True)
            child = safe_https_url(urljoin(child, first_playlist_uri(variant.decode("utf-8-sig", errors="replace"))))
        segment, _ = await self._fetch(child, MAX_FRAME_BYTES, cors=True, sample=True)
        if not segment:
            raise ProbeFailure("empty_segment")

    async def iframe(self, url: str, embed_host: str | None, verified: bool) -> None:
        if not embed_host or urlsplit(url).hostname != embed_host:
            raise ProbeFailure("embed_host_mismatch")
        _, headers = await self._fetch(url, 0, cors=False, sample=True)
        if not frame_policy_allows(headers, self.origin):
            raise ProbeFailure("frame_denied")
        if not verified:
            raise ProbeFailure("embed_unverified")

    async def check(self, playback_type: str, url: str, *, embed_host: str | None = None, embed_verified: bool = False) -> ProbeResult:
        start = time.monotonic()
        try:
            if playback_type == "hls":
                await self.hls(url)
            elif playback_type == "iframe":
                await self.iframe(url, embed_host, embed_verified)
            else:
                raise ProbeFailure("gateway_required")
            return ProbeResult("online", "ok", int((time.monotonic() - start) * 1000))
        except ProbeFailure as exc:
            status = "unknown" if exc.code in ("embed_unverified", "gateway_required") else "offline"
            return ProbeResult(status, exc.code, int((time.monotonic() - start) * 1000))
