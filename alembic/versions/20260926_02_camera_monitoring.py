"""Source rights and camera monitoring history.

Revision ID: 20260926_02
Revises: 20260926_01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260926_02"
down_revision = "20260926_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("permission_evidence_url", sa.String(1000)))
    op.add_column("sources", sa.Column("permission_reviewed_at", sa.DateTime(timezone=True)))
    op.add_column("sources", sa.Column("embed_host", sa.String(255)))
    op.add_column("cameras", sa.Column("last_success_at", sa.DateTime(timezone=True)))
    op.add_column("cameras", sa.Column("next_check_at", sa.DateTime(timezone=True)))
    op.add_column("cameras", sa.Column("last_error_code", sa.String(80)))
    op.add_column("cameras", sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("cameras", sa.Column("embed_verified_at", sa.DateTime(timezone=True)))
    op.add_column("cameras", sa.Column("unpublished_reason", sa.String(80)))
    op.create_table(
        "camera_checks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("camera_id", sa.Integer(), sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
    )
    op.create_index("ix_camera_checks_camera_time", "camera_checks", ["camera_id", "checked_at"])
    op.create_table(
        "camera_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("camera_id", sa.Integer(), sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("contact", sa.String(255)),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("resolution", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('open', 'resolved')", name="ck_camera_reports_status"),
    )
    op.create_index("ix_camera_reports_status_time", "camera_reports", ["status", "created_at"])


def downgrade() -> None:
    op.drop_table("camera_reports")
    op.drop_table("camera_checks")
    for column in ("unpublished_reason", "embed_verified_at", "consecutive_failures", "last_error_code", "next_check_at", "last_success_at"):
        op.drop_column("cameras", column)
    for column in ("embed_host", "permission_reviewed_at", "permission_evidence_url"):
        op.drop_column("sources", column)
