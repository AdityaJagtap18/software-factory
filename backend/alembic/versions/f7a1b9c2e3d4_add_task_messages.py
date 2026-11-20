"""add task_messages table

Revision ID: f7a1b9c2e3d4
Revises: d6f03b2c8a91
Create Date: 2026-11-20 00:00:00.000002

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f7a1b9c2e3d4'
down_revision: Union[str, None] = 'd6f03b2c8a91'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLAlchemy's Enum type stores the Python member NAME (uppercase) by
    # default, not its .value -- matching every other enum column in this
    # codebase (task_status, task_priority, ...), so the Postgres labels
    # here must be uppercase too.
    task_message_role = postgresql.ENUM('USER', 'AGENT', 'SYSTEM', name='task_message_role')

    op.create_table(
        'task_messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', task_message_role, nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_by_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_task_messages_task_id', 'task_messages', ['task_id'])


def downgrade() -> None:
    op.drop_index('ix_task_messages_task_id', table_name='task_messages')
    op.drop_table('task_messages')
    postgresql.ENUM(name='task_message_role').drop(op.get_bind(), checkfirst=True)
