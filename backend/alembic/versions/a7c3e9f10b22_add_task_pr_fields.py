"""add task pull request fields

Revision ID: a7c3e9f10b22
Revises: f1a2b3c4d5e6
Create Date: 2026-11-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7c3e9f10b22'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tasks', sa.Column('git_pr_url', sa.String(length=500), nullable=False, server_default=''))
    op.add_column('tasks', sa.Column('git_pr_number', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('tasks', 'git_pr_number')
    op.drop_column('tasks', 'git_pr_url')
