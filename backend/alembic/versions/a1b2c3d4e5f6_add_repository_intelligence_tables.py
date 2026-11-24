"""add repository intelligence tables

Revision ID: a1b2c3d4e5f6
Revises: e8b1c2d3f4a5
Create Date: 2026-11-20 00:00:00.000004

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'e8b1c2d3f4a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'repository_intelligence_settings',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('repository_connection_id', UUID(as_uuid=True), sa.ForeignKey('repository_connections.id', ondelete='CASCADE'), nullable=False),
        sa.Column('default_branch', sa.String(255), nullable=False, server_default='main'),
        sa.Column('included_paths', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('excluded_paths', sa.JSON(), nullable=False, server_default='["node_modules", "dist", ".git", "__pycache__", "venv", ".venv", "build"]'),
        sa.Column('max_file_size_kb', sa.Integer(), nullable=False, server_default='500'),
        sa.Column('auto_index_on_sync', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('project_id', 'repository_connection_id', name='uq_repo_intelligence_settings'),
    )

    op.create_table(
        'repository_indexing_runs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('repository_connection_id', UUID(as_uuid=True), sa.ForeignKey('repository_connections.id', ondelete='CASCADE'), nullable=False),
        sa.Column('branch', sa.String(255), nullable=False),
        sa.Column('commit_sha', sa.String(100), nullable=False, server_default=''),
        sa.Column('status', sa.String(50), nullable=False, server_default='RUNNING'),
        sa.Column('graphify_version', sa.String(50), nullable=False, server_default='0.9.113'),
        sa.Column('entities_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('relationships_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('duration_seconds', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('log_output', sa.Text(), nullable=False, server_default=''),
        sa.Column('error_message', sa.Text(), nullable=False, server_default=''),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('repository_indexing_runs')
    op.drop_table('repository_intelligence_settings')
