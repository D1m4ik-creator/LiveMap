import importlib.util
from pathlib import Path

import pytest

from livemap.api.errors import APIError
from livemap.core.config import get_settings
from livemap.db.models import Camera, Source
from livemap.services.source_rules import ensure_camera_publishable, public_stream_binding
from datetime import datetime, timezone


spec = importlib.util.spec_from_file_location("media_gateway", Path(__file__).resolve().parents[1] / "deploy/media/gateway.py")
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


def resolved(*args, **kwargs):
    return [(2, 1, 6, "", ("8.8.8.8", 554))]


def environment():
    return {"LIVEMAP_RTSP_UPSTREAM": "rtsp://user:secret@camera.example/live",
            "LIVEMAP_RTSP_ALLOWED_HOST": "camera.example", "PUBLIC_ORIGIN": "https://livemap.example"}


def test_gateway_fixed_read_only_path_and_dns_pin():
    config = gateway.build_config(environment(), resolve=resolved)
    assert config["paths"]["camera1"]["source"] == "rtsp://user:secret@8.8.8.8:554/live"
    assert list(config["paths"]) == ["camera1"]
    assert config["paths"]["camera1"]["sourceOnDemand"] is True
    assert config["hlsAllowOrigins"] == ["https://livemap.example"]
    assert all(config[key] is False for key in ("api", "metrics", "pprof", "playback", "rtsp", "webrtc", "rtmp", "srt", "moq"))
    assert config["authInternalUsers"][0]["permissions"] == [{"action": "read", "path": "camera1"}]


def test_gateway_rejects_private_and_mixed_dns_even_with_public_host():
    for addresses in (["127.0.0.1"], ["8.8.8.8", "169.254.169.254"], ["::1"], ["10.1.1.1"]):
        with pytest.raises(ValueError):
            gateway.build_config(environment(), resolve=lambda *a, **kw: [(2, 1, 6, "", (ip, 554)) for ip in addresses])
    env = environment()
    env["LIVEMAP_RTSP_ALLOWED_HOST"] = "another.example"
    with pytest.raises(ValueError):
        gateway.build_config(env, resolve=resolved)


def test_gateway_hides_credentials_in_errors_and_logs():
    source = "rtsp://user:secret@camera.example/live"
    line = gateway.redact(f"failed {source}; secret; rtsp://user:secret@8.8.8.8:554/live", source)
    assert "secret" not in line and "rtsp://" not in line and "user" not in line
    for origin in ("*", "https://*.example", "http://livemap.example", "https://livemap.example/path"):
        with pytest.raises(ValueError):
            gateway.build_config({**environment(), "PUBLIC_ORIGIN": origin}, resolve=resolved)


def test_only_configured_public_gateway_can_use_upstream_reference(monkeypatch):
    monkeypatch.setattr(get_settings(), "media_gateway_public_base", "https://media.example")
    source = Source(is_approved=True, stream_url="https://media.example/camera1/index.m3u8",
                    secret_ref="LIVEMAP_RTSP_UPSTREAM", permission_evidence_url="https://owner.example/",
                    permission_reviewed_at=datetime.now(timezone.utc), removal_contact="owner@example.org")
    assert public_stream_binding(source)
    ensure_camera_publishable(Camera(playback_type="hls"), source)
    for url, reference in (("rtsp://owner.example/live", "LIVEMAP_RTSP_UPSTREAM"),
                           ("https://other.example/camera1/index.m3u8", "LIVEMAP_RTSP_UPSTREAM"),
                           ("https://media.example/camera1/index.m3u8?token=abc", "LIVEMAP_RTSP_UPSTREAM"),
                           ("https://media.example/camera1/index.m3u8", "PRIVATE_STREAM_KEY")):
        source.stream_url, source.secret_ref = url, reference
        assert not public_stream_binding(source)
        with pytest.raises(APIError):
            ensure_camera_publishable(Camera(playback_type="hls"), source)
    source.stream_url, source.secret_ref = "https://media.example/camera1/index.m3u8", "LIVEMAP_RTSP_UPSTREAM"
    with pytest.raises(APIError):
        ensure_camera_publishable(Camera(playback_type="iframe"), source)
    monkeypatch.setattr(get_settings(), "media_gateway_public_base", None)
    assert not public_stream_binding(source)
