"""merge repository-intelligence/task-model branch with phase6 head

Revision ID: aaaeebdc9faf
Revises: 51e63e34dee0, d42e13a77792
Create Date: 2026-11-24 05:30:11.705917

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'aaaeebdc9faf'
down_revision: Union[str, None] = ('51e63e34dee0', 'd42e13a77792')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
