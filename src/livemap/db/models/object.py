from __future__ import annotations

from typing import TYPE_CHECKING

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from livemap.db.base import Base

if TYPE_CHECKING:
    from livemap.db.models.camera import Camera

class Object(Base):
    __tablename__ = "objects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    geometry: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True),
        nullable=False,
    )

    cameras: Mapped[list["Camera"]] = relationship(
        "Camera",
        back_populates="object",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
