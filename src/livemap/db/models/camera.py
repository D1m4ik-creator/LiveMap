from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from livemap.db.base import Base

if TYPE_CHECKING:
    from livemap.db.models.place import Place
    from livemap.db.models.source import Source


class Camera(Base):
    __tablename__ = "cameras"
    __table_args__ = (
        CheckConstraint("playback_type IN ('hls', 'iframe', 'rtsp')", name="ck_cameras_playback_type"),
        CheckConstraint("status IN ('online', 'offline', 'unknown')", name="ck_cameras_status"),
        Index("ix_cameras_public", "place_id", "is_published", "status"),
        Index("ix_cameras_source_id", "source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    place_id: Mapped[int] = mapped_column(ForeignKey("places.id", ondelete="CASCADE"), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    playback_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="unknown", nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    embed_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unpublished_reason: Mapped[str | None] = mapped_column(String(80))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    place: Mapped["Place"] = relationship(back_populates="cameras")
    source: Mapped["Source"] = relationship(back_populates="cameras")
