"""Bounded, DNS-pinned probes for approved public camera sources.

Never use this module as a user-supplied URL fetcher. It deliberately refuses
redirects, private DNS answers, URL credentials and HTTP downgrades.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl, urljoin, urlsplit

import aiohttp

from livemap.api.errors import APIError
from livemap.services.source_rules import public_iframe_query_allowed, validate_url


MAX_MANIFEST_BYTES = 256 * 1024
MAX_FRAME_BYTES = 16 * 1024
MAX_PROVIDER_STATUS_BYTES = 256 * 1024
RUTUBE_EMBED_PATH = re.compile(r"/play/embed/([0-9a-f]{32})/?\Z")


class ProbeFailure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ProbeResult:
    status: str
    code: str
    duration_ms: int


def safe_https_url(value: str, *, allow_query: bool = False) -> str:
    try:
        validate_url(value, {"https"})
    except APIError as exc:
        raise ProbeFailure("unsafe_url") from exc
    if urlsplit(value).query and not allow_query:
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


def require_live_playlist(manifest: str) -> None:
    if "#EXT-X-ENDLIST" in manifest or "#EXT-X-PLAYLIST-TYPE:VOD" in manifest:
        raise ProbeFailure("not_live_stream")


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


def rutube_embed_id(url: str) -> str | None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https" or parsed.hostname != "rutube.ru" or parsed.port is not None
        or parsed.username or parsed.password or parsed.query or parsed.fragment
    ):
        return None
    match = RUTUBE_EMBED_PATH.fullmatch(parsed.path)
    return match.group(1) if match else None


def rutube_live_available(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    access = payload.get("acl_access")
    streams = payload.get("live_streams")
    return (
        payload.get("stream_type") == "broadcast"
        and payload.get("has_video") is True
        and payload.get("is_hidden") is False
        and isinstance(access, dict) and access.get("allowed") is True
        and isinstance(streams, dict) and isinstance(streams.get("hls"), list)
        and bool(streams["hls"])
    )


def vk_embed_redirect_allowed(target: str, original: str) -> bool:
    try:
        safe_https_url(target, allow_query=True)
        parsed = urlsplit(target)
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        values = dict(pairs)
        if parsed.port is not None or len(values) != len(pairs):
            return False
        if target == original:
            return public_iframe_query_allowed(target, "vkvideo.ru")
        if parsed.hostname == "login.vk.ru" and parsed.path == "/":
            return (
                set(values) == {"act", "redirect_uri", "state", "uuid", "app_id"}
                and values["act"] == "autologin"
                and values["redirect_uri"] == "https://vkvideo.ru"
                and values["app_id"].isdigit()
            )
        return (
            parsed.hostname == "vkvideo.ru" and parsed.path in {"", "/"}
            and set(values) == {"errorCode", "errorText", "state"}
        )
    except ProbeFailure:
        return False


class CameraProbe:
    def __init__(self, origin: str) -> None:
        self.origin = origin.rstrip("/")
        timeout = aiohttp.ClientTimeout(total=12, connect=5, sock_read=5)
        connector = aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False, limit=4)
        self.client = aiohttp.ClientSession(
            connector=connector, timeout=timeout, trust_env=False,
            headers={"User-Agent": "LiveMap-availability/1.0"},
        )

    async def __aenter__(self) -> CameraProbe:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.client.close()

    async def _fetch(self, url: str, limit: int, *, cors: bool, sample: bool = False,
                     allow_query: bool = False, referer: str | None = None) -> tuple[bytes, aiohttp.typedefs.LooseHeaders]:
        safe_https_url(url, allow_query=allow_query)
        try:
            headers = {}
            if cors:
                headers["Origin"] = self.origin
            if referer:
                headers["Referer"] = referer
            async with self.client.get(
                url, allow_redirects=False, headers=headers or None
            ) as response:
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
            manifest = variant.decode("utf-8-sig", errors="replace")
            child = safe_https_url(urljoin(child, first_playlist_uri(manifest)))
        require_live_playlist(manifest)
        segment, _ = await self._fetch(child, MAX_FRAME_BYTES, cors=True, sample=True)
        if not segment:
            raise ProbeFailure("empty_segment")

    async def vk_embed(self, url: str) -> aiohttp.typedefs.LooseHeaders:
        """VK's public embed initializes anonymous cookies on its login host.

        Accept only this bounded provider handshake; the final URL must be the
        original public embed. Other probes still reject every redirect.
        """
        current = url
        try:
            async with asyncio.timeout(12):
                for hop in range(4):
                    safe_https_url(current, allow_query=True)
                    async with self.client.get(current, allow_redirects=False, headers={"Referer": f"{self.origin}/"}) as response:
                        if 300 <= response.status < 400:
                            target = urljoin(current, response.headers.get("Location", ""))
                            if hop == 3 or not vk_embed_redirect_allowed(target, url):
                                raise ProbeFailure("redirect_rejected")
                            current = target
                            continue
                        if response.status != 200 or current != url:
                            raise ProbeFailure("http_error")
                        return response.headers
        except ProbeFailure:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            raise ProbeFailure("connection_failed") from exc
        raise ProbeFailure("redirect_rejected")

    async def iframe(self, url: str, embed_host: str | None, verified: bool) -> None:
        if not embed_host or urlsplit(url).hostname != embed_host:
            raise ProbeFailure("embed_host_mismatch")
        if not public_iframe_query_allowed(url, embed_host):
            raise ProbeFailure("signed_url_requires_gateway")
        if embed_host == "vkvideo.ru":
            headers = await self.vk_embed(url)
        else:
            _, headers = await self._fetch(url, 0, cors=False, sample=True, allow_query=True)
        if not frame_policy_allows(headers, self.origin):
            raise ProbeFailure("frame_denied")
        if not verified:
            raise ProbeFailure("embed_unverified")
        if embed_host == "rutube.ru":
            video_id = rutube_embed_id(url)
            if video_id is None:
                raise ProbeFailure("invalid_provider_embed")
            body, _ = await self._fetch(
                f"https://rutube.ru/api/play/options/{video_id}", MAX_PROVIDER_STATUS_BYTES,
                cors=False, referer=f"{self.origin}/",
            )
            try:
                options = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProbeFailure("invalid_provider_status") from exc
            if not rutube_live_available(options):
                raise ProbeFailure("provider_offline")

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
