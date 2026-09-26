import socket

import pytest

from livemap.services.camera_probe import (
    ProbeFailure, cors_allowed, first_playlist_uri, frame_policy_allows,
    public_dns_answers, rutube_embed_id, rutube_live_available, safe_https_url,
)
from livemap.services.source_rules import public_iframe_query_allowed


def test_probe_rejects_private_dns_even_when_mixed_with_public() -> None:
    answers = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443)),
    ]
    with pytest.raises(ProbeFailure, match="private_address"):
        public_dns_answers("camera.example", 443, answers)


def test_probe_rejects_signed_and_non_https_urls() -> None:
    for url in (
        "http://example.org/live.m3u8",
        "https://example.org/live.m3u8?token=abc",
        "https://127.0.0.1/live.m3u8",
    ):
        with pytest.raises(ProbeFailure):
            safe_https_url(url)


def test_only_known_public_iframe_query_is_allowed() -> None:
    url = "https://open.ivideon.com/embed/v3/?camera=0&server=100-8fc028e011c3992b792d655e57a42947&lang=ru&width=&height="
    assert public_iframe_query_allowed(url, "open.ivideon.com")
    assert safe_https_url(url, allow_query=True) == url
    for unsafe in (
        "https://open.ivideon.com/embed/v3/?camera=0&server=public&token=secret",
        "https://open.ivideon.com/embed/v3/?camera=0&camera=1&server=public",
        "https://open.ivideon.com/embed/v3/?camera=0&server=public&session=secret",
        "https://other.example/embed/v3/?camera=0&server=public",
    ):
        assert not public_iframe_query_allowed(unsafe, "open.ivideon.com")


def test_playlist_and_browser_headers() -> None:
    assert first_playlist_uri("#EXTM3U\n#EXTINF:6,\nsegment.ts\n") == "segment.ts"
    with pytest.raises(ProbeFailure, match="invalid_manifest"):
        first_playlist_uri("<html>oops</html>")
    assert cors_allowed("https://livemap.example", "https://livemap.example")
    assert not cors_allowed(None, "https://livemap.example")
    assert not frame_policy_allows({"X-Frame-Options": "DENY"}, "https://livemap.example")
    assert not frame_policy_allows({"Content-Security-Policy": "frame-ancestors 'self'"}, "https://livemap.example")
    assert frame_policy_allows({"Content-Security-Policy": "frame-ancestors https://livemap.example"}, "https://livemap.example")


def test_rutube_live_status_requires_public_active_broadcast() -> None:
    embed = "https://rutube.ru/play/embed/627e3e6cfcbdf991f5bc560182570dfc"
    assert rutube_embed_id(embed) == "627e3e6cfcbdf991f5bc560182570dfc"
    assert rutube_embed_id(embed + "?p=private") is None
    assert rutube_embed_id(embed.replace("https://", "http://")) is None
    assert rutube_embed_id("https://rutube.ru/play/embed/not-an-id") is None
    active = {
        "stream_type": "broadcast", "has_video": True, "is_hidden": False,
        "acl_access": {"allowed": True}, "live_streams": {"hls": [{"url": "https://example.org/live"}]},
    }
    assert rutube_live_available(active)
    assert not rutube_live_available({**active, "live_streams": {"hls": []}})
    assert not rutube_live_available({**active, "acl_access": {"allowed": False}})
    assert not rutube_live_available({**active, "stream_type": "video"})
