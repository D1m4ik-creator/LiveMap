import socket
import asyncio

import pytest

from livemap.services.camera_probe import (
    CameraProbe, ProbeFailure, cors_allowed, first_playlist_uri, frame_policy_allows,
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


def test_ipeye_public_player_rejects_extra_or_changed_parameters() -> None:
    url = "https://ipeye.ru/ipeye_service/api/iframe.php?iframe_player=1&dev=243eafa8f63049408a996398bec79228&autoplay=0&archive=1"
    assert public_iframe_query_allowed(url, "ipeye.ru")
    for unsafe in (
        url + "&token=secret",
        url.replace("autoplay=0", "autoplay=1"),
        url.replace("archive=1", "archive=0"),
        url.replace("dev=243eafa8f63049408a996398bec79228", "dev=not-a-public-id"),
        url.replace("https://ipeye.ru", "https://ipeye.ru:8443"),
        url.replace("iframe.php", "private.php"),
    ):
        assert not public_iframe_query_allowed(unsafe, "ipeye.ru")


def test_playlist_and_browser_headers() -> None:
    assert first_playlist_uri("#EXTM3U\n#EXTINF:6,\nsegment.ts\n") == "segment.ts"
    with pytest.raises(ProbeFailure, match="invalid_manifest"):
        first_playlist_uri("<html>oops</html>")
    assert cors_allowed("https://livemap.example", "https://livemap.example")
    assert not cors_allowed(None, "https://livemap.example")
    assert not frame_policy_allows({"X-Frame-Options": "DENY"}, "https://livemap.example")
    assert not frame_policy_allows({"Content-Security-Policy": "frame-ancestors 'self'"}, "https://livemap.example")
    assert frame_policy_allows({"Content-Security-Policy": "frame-ancestors https://livemap.example"}, "https://livemap.example")


def test_alliance_and_vk_only_accept_public_embed_parameters() -> None:
    alliance = "https://glaz.inetvl.ru/embed/v3/?server=100-88QTJdHdYh0SMFStxFyBSG&camera=0&width=&height=&lang=ru"
    vk = "https://vkvideo.ru/video_ext.php?oid=-143491903&id=456240452&hash=bde71b469d8fa2a7&hd=3"
    assert public_iframe_query_allowed(alliance, "glaz.inetvl.ru")
    assert public_iframe_query_allowed(vk, "vkvideo.ru")
    for value, host in ((alliance, "glaz.inetvl.ru"), (vk, "vkvideo.ru")):
        assert not public_iframe_query_allowed(value + "&access_key=private", host)
        assert not public_iframe_query_allowed(value + "&token=secret", host)
        assert not public_iframe_query_allowed(value.replace("https://", "http://"), host)
        assert not public_iframe_query_allowed(value.replace(host, "other.example"), host)
    assert not public_iframe_query_allowed(vk.replace("hd=3", "hd=3&hd=4"), "vkvideo.ru")
    assert not public_iframe_query_allowed(vk.replace("bde71b469d8fa2a7", "invalid"), "vkvideo.ru")


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


def test_rutube_probe_checks_embed_for_public_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(self, url, _limit, *, cors, sample=False, allow_query=False, referer=None):
        assert not cors
        if "/play/embed/" in url:
            assert referer is None
            return b"", {}
        assert "/api/play/options/" in url
        assert referer == "http://localhost:5173/"
        raise ProbeFailure("http_error")

    monkeypatch.setattr(CameraProbe, "_fetch", fake_fetch)

    async def run() -> None:
        async with CameraProbe("http://localhost:5173") as probe:
            result = await probe.check(
                "iframe", "https://rutube.ru/play/embed/627e3e6cfcbdf991f5bc560182570dfc",
                embed_host="rutube.ru", embed_verified=True,
            )
            assert result.status == "offline"
            assert result.code == "http_error"

    asyncio.run(run())
