"""job usage

Revision ID: 0003
Revises: 0002

Plan 6B：每個有回應的 Gemini 請求一筆用量與費用（Plan 7 加上 ComfyUI 的 GPU 秒數）。
需求拆解還沒有任務，job_id 為空；任務刪除時一併刪除。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0003'
down_revision: str | Sequence[str] | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'job_usage',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('job_id', sa.String(), nullable=True),
        sa.Column('brand_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('model', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('round', sa.Integer(), nullable=True),
        sa.Column('target', sa.String(), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=False),
        sa.Column('cached_tokens', sa.Integer(), nullable=False),
        sa.Column('output_tokens', sa.Integer(), nullable=False),
        sa.Column('thinking_tokens', sa.Integer(), nullable=False),
        sa.Column('seconds', sa.Float(), nullable=True),
        sa.Column('cost_usd', sa.Numeric(precision=12, scale=6), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_job_usage_created_at'), 'job_usage', ['created_at'], unique=False)
    op.create_index(op.f('ix_job_usage_job_id'), 'job_usage', ['job_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_job_usage_job_id'), table_name='job_usage')
    op.drop_index(op.f('ix_job_usage_created_at'), table_name='job_usage')
    op.drop_table('job_usage')
