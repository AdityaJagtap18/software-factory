"""add task git worktree fields

Revision ID: f1a2b3c4d5e6
Revises: cbdd47b3f9aa
Create Date: 2026-11-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'cbdd47b3f9aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tasks', sa.Column('git_branch_name', sa.String(length=255), nullable=False, server_default=''))
    op.add_column('tasks', sa.Column('git_base_branch', sa.String(length=255), nullable=False, server_default=''))
    op.add_column('tasks', sa.Column('git_diff', sa.Text(), nullable=False, server_default=''))
    op.add_column('tasks', sa.Column('git_changed_files', sa.JSON(), nullable=False, server_default='[]'))


def downgrade() -> None:
    op.drop_column('tasks', 'git_changed_files')
    op.drop_column('tasks', 'git_diff')
    op.drop_column('tasks', 'git_base_branch')
    op.drop_column('tasks', 'git_branch_name')
