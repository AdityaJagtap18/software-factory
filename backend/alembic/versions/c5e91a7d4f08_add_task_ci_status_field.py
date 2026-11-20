"""add task ci status field

Revision ID: c5e91a7d4f08
Revises: b4d8f21e6c33
Create Date: 2026-11-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5e91a7d4f08'
down_revision: Union[str, None] = 'b4d8f21e6c33'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tasks', sa.Column('git_ci_status', sa.String(length=20), nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('tasks', 'git_ci_status')
