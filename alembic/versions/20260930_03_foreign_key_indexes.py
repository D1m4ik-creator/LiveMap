"""Cover catalog and administration foreign keys.

Revision ID: 20260930_03
Revises: 20260926_02
"""

from alembic import op

revision = "20260930_03"
down_revision = "20260926_02"
branch_labels = None
depends_on = None

INDEXES = (
    ("admin_sessions", "user_id"),
    ("audit_events", "actor_id"),
    ("camera_reports", "camera_id"),
    ("cameras", "source_id"),
)


def upgrade() -> None:
    for table, column in INDEXES:
        # The cloud advisor remediation may have run before this release.
        op.create_index(f"ix_{table}_{column}", table, [column], if_not_exists=True)


def downgrade() -> None:
    for table, column in reversed(INDEXES):
        op.drop_index(f"ix_{table}_{column}", table, if_exists=True)
