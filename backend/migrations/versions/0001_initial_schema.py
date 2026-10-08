"""initial schema

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'brands',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('source_hash', sa.String(), nullable=False),
        sa.Column('active', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'jobs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('brand_id', sa.String(), nullable=False),
        sa.Column('input', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('stage', sa.String(), nullable=False),
        sa.Column('round', sa.Integer(), server_default='0', nullable=False),
        sa.Column('finished', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('best_render_ids', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('last_seq', sa.Integer(), server_default='0', nullable=False),
        sa.Column('cancel_requested', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_jobs_brand_id'), 'jobs', ['brand_id'], unique=False)
    op.create_index(op.f('ix_jobs_created_at'), 'jobs', ['created_at'], unique=False)
    op.create_table(
        'brand_chunks',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('brand_id', sa.String(), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('section', sa.String(), nullable=False),
        sa.Column('tag', sa.String(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('origin', sa.String(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['brand_id'], ['brands.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_brand_chunks_brand_id'), 'brand_chunks', ['brand_id'], unique=False)
    op.create_table(
        'history',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('job_id', sa.String(), nullable=False),
        sa.Column('brand_id', sa.String(), nullable=False),
        sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('selected_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_history_brand_id'), 'history', ['brand_id'], unique=False)
    op.create_index(op.f('ix_history_selected_at'), 'history', ['selected_at'], unique=False)
    op.create_table(
        'job_events',
        sa.Column('job_id', sa.String(), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column('type', sa.String(), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('job_id', 'seq'),
    )
    op.create_table(
        'products',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('brand_id', sa.String(), nullable=False),
        sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('sample', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['brand_id'], ['brands.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_products_brand_id'), 'products', ['brand_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_products_brand_id'), table_name='products')
    op.drop_table('products')
    op.drop_table('job_events')
    op.drop_index(op.f('ix_history_selected_at'), table_name='history')
    op.drop_index(op.f('ix_history_brand_id'), table_name='history')
    op.drop_table('history')
    op.drop_index(op.f('ix_brand_chunks_brand_id'), table_name='brand_chunks')
    op.drop_table('brand_chunks')
    op.drop_index(op.f('ix_jobs_created_at'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_brand_id'), table_name='jobs')
    op.drop_table('jobs')
    op.drop_table('brands')
