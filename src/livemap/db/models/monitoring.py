from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from livemap.db.base import Base


class CameraCheck(Base):
    __tablename__ = "camera_checks"
    __table_args__ = (Index("ix_camera_checks_camera_time", "camera_id", "checked_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)


class CameraReport(Base):
    __tablename__ = "camera_reports"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'resolved')", name="ck_camera_reports_status"),
        Index("ix_camera_reports_status_time", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False)
    contact: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    resolution: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
