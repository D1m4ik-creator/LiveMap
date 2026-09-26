from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from livemap.db.base import Base

if TYPE_CHECKING:
    from livemap.db.models.camera import Camera


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_name: Mapped[str] = mapped_column(String(255), nullable=False)
    public_page_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    stream_url: Mapped[str | None] = mapped_column(String(1000))
    secret_ref: Mapped[str | None] = mapped_column(String(160))
    attribution: Mapped[str] = mapped_column(String(255), nullable=False)
    permission_note: Mapped[str] = mapped_column(Text, nullable=False)
    permission_evidence_url: Mapped[str | None] = mapped_column(String(1000))
    permission_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embed_host: Mapped[str | None] = mapped_column(String(255))
    permission_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removal_contact: Mapped[str | None] = mapped_column(String(255))
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    cameras: Mapped[list[Camera]] = relationship(back_populates="source")
