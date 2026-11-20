"""add task pull request state field

Revision ID: b4d8f21e6c33
Revises: a7c3e9f10b22
Create Date: 2026-11-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b4d8f21e6c33'
down_revision: Union[str, None] = 'a7c3e9f10b22'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tasks', sa.Column('git_pr_state', sa.String(length=20), nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('tasks', 'git_pr_state')
