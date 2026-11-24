"""add documents and document_chunks tables with pgvector

Revision ID: 8a0dcf3b06fb
Revises: 55ce85427eb0
Create Date: 2026-11-21 11:37:40.167907

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy


revision: str = '8a0dcf3b06fb'
down_revision: Union[str, None] = '55ce85427eb0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.create_table('documents',
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('source_filename', sa.String(length=255), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('created_by_user_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('document_chunks',
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.Vector(768), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_document_chunks_project_id', 'document_chunks', ['project_id'], unique=False)
    # HNSW index on cosine distance -- matches the `cosine_distance()`
    # comparator used by document_retrieval.py's similarity search.
    op.execute(
        'CREATE INDEX ix_document_chunks_embedding_cosine ON document_chunks '
        'USING hnsw (embedding vector_cosine_ops)'
    )


def downgrade() -> None:
    op.drop_index('ix_document_chunks_embedding_cosine', table_name='document_chunks')
    op.drop_index('ix_document_chunks_project_id', table_name='document_chunks')
    op.drop_table('document_chunks')
    op.drop_table('documents')
