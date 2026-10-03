import ipaddress
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlsplit

from livemap.api.errors import APIError
from livemap.db.models import Camera, Source
from livemap.core.config import get_settings


SENSITIVE_QUERY_KEYS = {"token", "key", "api_key", "apikey", "password", "pass", "secret", "signature", "sig", "auth"}
IVIDEON_EMBED_HOST = "open.ivideon.com"
ALLIANCE_EMBED_HOST = "glaz.inetvl.ru"
VK_EMBED_HOST = "vkvideo.ru"
IVIDEON_EMBED_KEYS = {"camera", "server", "lang", "width", "height"}
IPEYE_EMBED_HOST = "ipeye.ru"
IPEYE_EMBED_KEYS = {"iframe_player", "dev", "autoplay", "archive"}
GATEWAY_SECRET_REF = "LIVEMAP_RTSP_UPSTREAM"


def gateway_playback_url() -> str | None:
    base = get_settings().media_gateway_public_base
    return f"{base}/camera1/index.m3u8" if base else None


def public_stream_binding(source: Source) -> bool:
    return source.secret_ref is None or (
        source.secret_ref == GATEWAY_SECRET_REF
        and gateway_playback_url() is not None
        and source.stream_url == gateway_playback_url()
    )


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


def validate_source_metadata(source: Source) -> None:
    validate_source_urls(source.public_page_url, source.stream_url)
    if source.permission_evidence_url:
        validate_url(source.permission_evidence_url, {"https"})
    if source.embed_host:
        host = source.embed_host.lower().rstrip(".")
        if host != source.embed_host or not source.stream_url or urlsplit(source.stream_url).hostname != host:
            raise APIError("invalid_embed_host", "Embed host must exactly match the stream URL host", 400)
        validate_url(f"https://{host}/", {"https"})


def public_iframe_query_allowed(value: str, embed_host: str | None) -> bool:
    """Allow only documented public player identifiers, never arbitrary queries."""
    parsed = urlsplit(value)
    if not parsed.query:
        return True
    if parsed.scheme != "https" or parsed.hostname != embed_host or parsed.port is not None:
        return False
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    keys = [key for key, _ in pairs]
    values = dict(pairs)
    if len(pairs) != len(set(keys)):
        return False
    if embed_host == IPEYE_EMBED_HOST and parsed.path == "/ipeye_service/api/iframe.php":
        dev = values.get("dev", "")
        return (
            set(keys) == IPEYE_EMBED_KEYS
            and values.get("iframe_player") == "1"
            and len(dev) == 32 and all(char in "0123456789abcdef" for char in dev)
            and values.get("autoplay") == "0"
            and values.get("archive") == "1"
        )
    if embed_host == VK_EMBED_HOST and parsed.path == "/video_ext.php":
        return (
            set(keys) == {"oid", "id", "hash", "hd"}
            and len(values["oid"]) <= 20 and values["oid"].removeprefix("-").isdigit()
            and len(values["id"]) <= 20 and values["id"].isdigit()
            and len(values["hash"]) == 16 and all(char in "0123456789abcdef" for char in values["hash"])
            and values["hd"] in {"0", "1", "2", "3", "4"}
        )
    if embed_host not in {IVIDEON_EMBED_HOST, ALLIANCE_EMBED_HOST} or parsed.path != "/embed/v3/":
        return False
    return (
        set(keys) <= IVIDEON_EMBED_KEYS
        and "camera" in values and values["camera"].isdigit()
        and "server" in values and len(values["server"]) <= 80
        and values["server"].replace("-", "").isalnum()
        and values.get("lang", "ru") in {"ru", "en"}
        and all(not values.get(key) or values[key].isdigit() for key in ("width", "height"))
    )


def ensure_source_publishable(source: Source) -> None:
    if not source.is_approved:
        raise APIError("source_not_approved", "Source must be approved before publication", 409)
    if not source.permission_evidence_url or not source.permission_reviewed_at or not source.removal_contact:
        raise APIError("rights_incomplete", "Permission evidence, review date and removal contact are required", 409)
    if source.permission_expires_at and source.permission_expires_at <= datetime.now(timezone.utc):
        raise APIError("permission_expired", "Source permission has expired", 409)
    if not source.stream_url:
        raise APIError("missing_stream", "Source has no stream URL", 409)
    if not public_stream_binding(source):
        raise APIError("gateway_required", "Source requires a media gateway", 409)


def ensure_camera_publishable(camera: Camera, source: Source) -> None:
    ensure_source_publishable(source)
    if source.secret_ref and camera.playback_type != "hls":
        raise APIError("gateway_required", "Gateway publication requires HTTPS HLS", 409)
    if camera.playback_type == "rtsp":
        raise APIError("gateway_required", "RTSP publication requires a media gateway", 409)
    if camera.valid_until and camera.valid_until <= datetime.now(timezone.utc):
        raise APIError("camera_expired", "Camera validity has expired", 409)
    validate_url(source.stream_url, {"https"})
    if camera.playback_type == "iframe" and not source.embed_host:
        raise APIError("embed_host_required", "Iframe publication requires an approved embed host", 409)
    if camera.playback_type == "iframe":
        if not public_iframe_query_allowed(source.stream_url, source.embed_host):
            raise APIError("gateway_required", "Iframe URL query is not approved for direct playback", 409)
    elif "?" in source.stream_url:
        raise APIError("gateway_required", "HLS URL with query parameters requires a media gateway", 409)
