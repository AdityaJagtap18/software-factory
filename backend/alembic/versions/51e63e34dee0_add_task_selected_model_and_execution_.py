"""add_task_selected_model_and_execution_history

Revision ID: 51e63e34dee0
Revises: a1b2c3d4e5f6
Create Date: 2026-11-20 17:55:03.875561

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '51e63e34dee0'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tasks', sa.Column('selected_model', sa.String(100), server_default='', nullable=False))
    op.add_column('tasks', sa.Column('execution_runtime', sa.String(100), server_default='', nullable=False))
    op.add_column('tasks', sa.Column('execution_history', sa.JSON(), server_default='[]', nullable=False))
    op.add_column('task_messages', sa.Column('model_id', sa.String(100), server_default='', nullable=False))
    op.add_column('task_messages', sa.Column('runtime_slug', sa.String(100), server_default='', nullable=False))


def downgrade() -> None:
    op.drop_column('task_messages', 'runtime_slug')
    op.drop_column('task_messages', 'model_id')
    op.drop_column('tasks', 'execution_history')
    op.drop_column('tasks', 'execution_runtime')
    op.drop_column('tasks', 'selected_model')
