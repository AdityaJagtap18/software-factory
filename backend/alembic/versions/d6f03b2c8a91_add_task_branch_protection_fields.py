"""add task branch protection fields

Revision ID: d6f03b2c8a91
Revises: c5e91a7d4f08
Create Date: 2026-11-20 00:00:00.000001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd6f03b2c8a91'
down_revision: Union[str, None] = 'c5e91a7d4f08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tasks', sa.Column('git_base_branch_protected', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('tasks', sa.Column('git_required_status_checks', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('tasks', sa.Column('git_required_approving_reviews', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('tasks', 'git_required_approving_reviews')
    op.drop_column('tasks', 'git_required_status_checks')
    op.drop_column('tasks', 'git_base_branch_protected')
