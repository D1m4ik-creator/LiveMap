import socket

import pytest

from livemap.services.camera_probe import (
    ProbeFailure, cors_allowed, first_playlist_uri, frame_policy_allows,
    public_dns_answers, safe_https_url,
)


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


def test_playlist_and_browser_headers() -> None:
    assert first_playlist_uri("#EXTM3U\n#EXTINF:6,\nsegment.ts\n") == "segment.ts"
    with pytest.raises(ProbeFailure, match="invalid_manifest"):
        first_playlist_uri("<html>oops</html>")
    assert cors_allowed("https://livemap.example", "https://livemap.example")
    assert not cors_allowed(None, "https://livemap.example")
    assert not frame_policy_allows({"X-Frame-Options": "DENY"}, "https://livemap.example")
    assert not frame_policy_allows({"Content-Security-Policy": "frame-ancestors 'self'"}, "https://livemap.example")
    assert frame_policy_allows({"Content-Security-Policy": "frame-ancestors https://livemap.example"}, "https://livemap.example")
