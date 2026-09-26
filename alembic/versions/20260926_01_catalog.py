"""Initial PostGIS catalog and administration tables.

Revision ID: 20260926_01
Revises:
"""

from alembic import op
import geoalchemy2
import sqlalchemy as sa


revision = "20260926_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.create_table(
        "places",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(160), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("address", sa.String(500)),
        sa.Column("city", sa.String(160), nullable=False),
        sa.Column("region", sa.String(160), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("geometry", geoalchemy2.Geometry("POINT", srid=4326, spatial_index=False), nullable=False),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("ST_X(geometry) BETWEEN -180 AND 180", name="ck_places_longitude"),
        sa.CheckConstraint("ST_Y(geometry) BETWEEN -90 AND 90", name="ck_places_latitude"),
    )
    op.create_index("ix_places_geometry", "places", ["geometry"], postgresql_using="gist")
    op.create_index("ix_places_city_region", "places", ["city", "region"])
    op.create_index("ix_places_published_category", "places", ["is_published", "category"])

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_name", sa.String(255), nullable=False),
        sa.Column("public_page_url", sa.String(1000), nullable=False),
        sa.Column("stream_url", sa.String(1000)),
        sa.Column("secret_ref", sa.String(160)),
        sa.Column("attribution", sa.String(255), nullable=False),
        sa.Column("permission_note", sa.Text(), nullable=False),
        sa.Column("permission_expires_at", sa.DateTime(timezone=True)),
        sa.Column("removal_contact", sa.String(255)),
        sa.Column("is_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "admin_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('admin', 'editor')", name="ck_admin_users_role"),
    )
    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_admin_sessions_expires_at", "admin_sessions", ["expires_at"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("admin_users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_id", sa.Integer()),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_events_entity", "audit_events", ["entity_type", "entity_id"])

    op.create_table(
        "cameras",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("place_id", sa.Integer(), sa.ForeignKey("places.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("playback_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("playback_type IN ('hls', 'iframe', 'rtsp')", name="ck_cameras_playback_type"),
        sa.CheckConstraint("status IN ('online', 'offline', 'unknown')", name="ck_cameras_status"),
    )
    op.create_index("ix_cameras_public", "cameras", ["place_id", "is_published", "status"])


def downgrade() -> None:
    op.drop_table("cameras")
    op.drop_table("audit_events")
    op.drop_table("admin_sessions")
    op.drop_table("admin_users")
    op.drop_table("sources")
    op.drop_table("places")
