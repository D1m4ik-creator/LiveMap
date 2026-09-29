import asyncio

from livemap.services.camera_probe import ProbeResult
from livemap.worker import DueCamera, check_due


def test_unexpected_probe_failure_is_recorded_without_stopping_batch(monkeypatch) -> None:
    results: list[tuple[int, ProbeResult]] = []

    class Probe:
        async def check(self, _kind, url, **_kwargs):
            if url.endswith("bad.m3u8"):
                raise RuntimeError("upstream session closed")
            return ProbeResult("online", "ok", 5)

    async def save(camera, result):
        results.append((camera.id, result))

    monkeypatch.setattr("livemap.worker.save_check", save)
    cameras = [
        DueCamera(1, 1, "hls", "https://example.org/bad.m3u8", None, False),
        DueCamera(2, 1, "hls", "https://example.org/good.m3u8", None, False),
    ]
    async def run() -> None:
        probe = Probe()
        await asyncio.gather(*(check_due(probe, camera) for camera in cameras))

    asyncio.run(run())
    assert [(camera_id, result.status, result.code) for camera_id, result in results] == [
        (1, "unknown", "probe_error"), (2, "online", "ok"),
    ]
