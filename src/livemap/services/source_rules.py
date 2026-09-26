import ipaddress
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlsplit

from livemap.api.errors import APIError
from livemap.db.models import Camera, Source


SENSITIVE_QUERY_KEYS = {"token", "key", "api_key", "apikey", "password", "pass", "secret", "signature", "sig", "auth"}


def validate_url(value: str, schemes: set[str]) -> str:
    if "\\" in value or any(ord(char) < 32 for char in value):
        raise APIError("invalid_url", "URL contains invalid characters", 400)
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise APIError("invalid_url", "URL is invalid", 400) from exc
    if parsed.scheme not in schemes or not host or not parsed.netloc or parsed.fragment:
        raise APIError("invalid_url", "URL must use an allowed protocol and have a public host", 400)
    if parsed.username or parsed.password or "@" in parsed.netloc or "%" in parsed.netloc:
        raise APIError("invalid_url", "URL credentials are not allowed", 400)
    if port is not None and not 1 <= port <= 65535:
        raise APIError("invalid_url", "URL port is invalid", 400)
    lowered = host.rstrip(".").lower()
    if "." not in lowered or lowered.endswith((".local", ".localhost", ".internal", ".invalid")):
        raise APIError("invalid_url", "URL host must be public", 400)
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise APIError("invalid_url", "Private or local addresses are not allowed", 400)
    if any(key.lower() in SENSITIVE_QUERY_KEYS for key, _ in parse_qsl(parsed.query, keep_blank_values=True)):
        raise APIError("invalid_url", "Credentials must not appear in URL query", 400)
    return value


def validate_source_urls(public_page_url: str, stream_url: str | None) -> None:
    validate_url(public_page_url, {"https"})
    if stream_url:
        validate_url(stream_url, {"https", "rtsp"})


def ensure_source_publishable(source: Source) -> None:
    if not source.is_approved:
        raise APIError("source_not_approved", "Source must be approved before publication", 409)
    if source.permission_expires_at and source.permission_expires_at <= datetime.now(timezone.utc):
        raise APIError("permission_expired", "Source permission has expired", 409)
    if not source.stream_url:
        raise APIError("missing_stream", "Source has no stream URL", 409)
    if source.secret_ref:
        raise APIError("gateway_required", "Source requires a media gateway", 409)
    if "?" in source.stream_url:
        raise APIError("gateway_required", "Stream URL with query parameters requires a media gateway", 409)


def ensure_camera_publishable(camera: Camera, source: Source) -> None:
    ensure_source_publishable(source)
    if camera.playback_type == "rtsp":
        raise APIError("gateway_required", "RTSP publication requires a media gateway", 409)
    if camera.valid_until and camera.valid_until <= datetime.now(timezone.utc):
        raise APIError("camera_expired", "Camera validity has expired", 409)
    validate_url(source.stream_url, {"https"})
