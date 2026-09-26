from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from livemap.db.base import Base

if TYPE_CHECKING:
    from livemap.db.models.camera import Camera


class Place(Base):
    __tablename__ = "places"
    __table_args__ = (
        CheckConstraint("ST_X(geometry) BETWEEN -180 AND 180", name="ck_places_longitude"),
        CheckConstraint("ST_Y(geometry) BETWEEN -90 AND 90", name="ck_places_latitude"),
        Index("ix_places_geometry", "geometry", postgresql_using="gist"),
        Index("ix_places_city_region", "city", "region"),
        Index("ix_places_published_category", "is_published", "category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(String(500))
    city: Mapped[str] = mapped_column(String(160), nullable=False)
    region: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    geometry: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    cameras: Mapped[list[Camera]] = relationship(back_populates="place", cascade="all, delete-orphan")
