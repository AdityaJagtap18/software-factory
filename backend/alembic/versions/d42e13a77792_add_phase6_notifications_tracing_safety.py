"""Phase 6: notifications, cost tracking / execution tracing, safety flags.

Revision ID: d42e13a77792
Revises: 64644fed887f
Create Date: 2026-11-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d42e13a77792"
down_revision = "64644fed887f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("link_url", sa.String(length=500), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])

    op.create_table(
        "task_execution_spans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_execution_attempts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("succeeded", sa.Boolean(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False),
    )
    op.create_index("ix_task_execution_spans_attempt_id", "task_execution_spans", ["attempt_id"])

    op.add_column(
        "task_execution_attempts",
        sa.Column("usage", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "tasks",
        sa.Column("safety_flags", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("tasks", "safety_flags")
    op.drop_column("task_execution_attempts", "usage")
    op.drop_index("ix_task_execution_spans_attempt_id", table_name="task_execution_spans")
    op.drop_table("task_execution_spans")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
