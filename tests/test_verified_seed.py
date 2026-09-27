import json
from datetime import datetime, timedelta, timezone

import pytest

from livemap.core.config import ROOT_DIR
from livemap.seed_verified import reviewed_embed


def test_reviewed_embed_requires_recent_public_rutube_evidence() -> None:
    now = datetime(2026, 9, 26, 9, 45, tzinfo=timezone.utc)
    item = {
        "publish_reviewed": True,
        "embed_verified_at": "2026-09-26T12:33:00+03:00",
        "stream_url": "https://rutube.ru/play/embed/86e2f45785378c866d212e7f5f5447b0",
        "embed_host": "rutube.ru",
        "public_page_url": "https://rutube.ru/live/video/86e2f45785378c866d212e7f5f5447b0/",
        "permission_evidence_url": "https://rutube.ru/info/embed/",
    }
    assert reviewed_embed(item, now) == datetime.fromisoformat(item["embed_verified_at"])
    with pytest.raises(ValueError):
        reviewed_embed({**item, "publish_reviewed": False}, now)
    with pytest.raises(ValueError):
        reviewed_embed({**item, "public_page_url": "https://rutube.ru/live/video/other/"}, now)
    with pytest.raises(ValueError):
        reviewed_embed(item, now + timedelta(days=8))


def test_provider_restricted_camera_is_not_seeded_as_verified() -> None:
    candidates = json.loads((ROOT_DIR / "demo" / "camera_candidates.json").read_text(encoding="utf-8"))
    restricted = next(item for item in candidates if item["slug"] == "novosibirsk-lenin-square-rutube")
    assert restricted["publish_reviewed"] is False
