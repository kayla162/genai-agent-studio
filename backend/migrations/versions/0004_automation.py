"""automation

Revision ID: 0004
Revises: 0003

Plan 9：任務的自動化欄位（client_ref、parent_job_id、reviewer_feedback）、
任務結束通知的 outbox，以及自動化 API 的冪等鍵。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0004'
down_revision: str | Sequence[str] | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('client_ref', sa.String(), nullable=True))
    op.add_column('jobs', sa.Column('parent_job_id', sa.String(), nullable=True))
    op.add_column('jobs', sa.Column('reviewer_feedback', sa.Text(), nullable=True))
    op.create_foreign_key('fk_jobs_parent_job_id', 'jobs', 'jobs', ['parent_job_id'], ['id'], ondelete='SET NULL')
    op.create_table(
        'webhook_outbox',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('job_id', sa.String(), nullable=False),
        sa.Column('event', sa.String(), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('job_id', 'event', name='uq_webhook_outbox_job_event'),
    )
    op.create_index('ix_webhook_outbox_due', 'webhook_outbox', ['status', 'next_attempt_at'], unique=False)
    op.create_table(
        'automation_requests',
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('job_id', sa.String(), nullable=False),
        sa.Column('response', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('key', 'action'),
    )
    op.create_index(op.f('ix_automation_requests_created_at'), 'automation_requests', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_automation_requests_created_at'), table_name='automation_requests')
    op.drop_table('automation_requests')
    op.drop_index('ix_webhook_outbox_due', table_name='webhook_outbox')
    op.drop_table('webhook_outbox')
    op.drop_constraint('fk_jobs_parent_job_id', 'jobs', type_='foreignkey')
    op.drop_column('jobs', 'reviewer_feedback')
    op.drop_column('jobs', 'parent_job_id')
    op.drop_column('jobs', 'client_ref')
