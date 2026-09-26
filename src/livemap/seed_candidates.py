"""Import researched camera candidates as unpublished drafts only."""

import asyncio
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from livemap.core.config import ROOT_DIR
from livemap.core.engine import close_engine, get_session_factory
from livemap.db.models import Camera, Place, Source
from livemap.services.catalog_admin import point
from livemap.services.source_rules import validate_source_metadata


async def seed() -> int:
    candidates = json.loads((ROOT_DIR / "demo" / "camera_candidates.json").read_text(encoding="utf-8"))
    count = 0
    async with get_session_factory()() as session:
        for item in candidates:
            existing = (await session.execute(select(Place).where(Place.slug == item["slug"]))).scalar_one_or_none()
            if existing is not None:
                if item["removal_contact"]:
                    source = (await session.execute(
                        select(Source).join(Camera, Camera.source_id == Source.id)
                        .where(Camera.place_id == existing.id, Source.owner_name == item["owner_name"])
                        .limit(1)
                    )).scalar_one_or_none()
                    if source and not source.is_approved and not source.removal_contact:
                        source.removal_contact = item["removal_contact"]
                continue
            place = Place(
                slug=item["slug"], name=item["name"], city=item["city"], region=item["region"],
                address=item["address"], category=item["category"],
                geometry=point(*item["coordinates"]), is_published=False,
            )
            source = Source(
                owner_name=item["owner_name"], public_page_url=item["public_page_url"],
                stream_url=item["stream_url"], embed_host=item["embed_host"],
                attribution=item["attribution"], permission_note=item["permission_note"],
                permission_evidence_url=item["permission_evidence_url"],
                permission_reviewed_at=datetime.fromisoformat(item["permission_reviewed_at"]),
                removal_contact=item["removal_contact"], is_approved=False,
            )
            validate_source_metadata(source)
            session.add_all((place, source))
            await session.flush()
            session.add(Camera(
                place_id=place.id, source_id=source.id, name=item["camera_name"],
                playback_type=item["playback_type"], status="unknown", is_published=False,
            ))
            count += 1
        await session.commit()
    return count


async def run() -> None:
    try:
        count = await seed()
        print(f"Added {count} unpublished camera candidates")
    finally:
        await close_engine()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
