"""add task knowledge_context column

Revision ID: e8b1c2d3f4a5
Revises: f7a1b9c2e3d4
Create Date: 2026-11-20 00:00:00.000003

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e8b1c2d3f4a5'
down_revision: Union[str, None] = 'f7a1b9c2e3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tasks',
        sa.Column('knowledge_context', sa.JSON(), nullable=False, server_default='{}'),
    )
    op.alter_column('tasks', 'knowledge_context', server_default=None)


def downgrade() -> None:
    op.drop_column('tasks', 'knowledge_context')
