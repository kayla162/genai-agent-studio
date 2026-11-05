"""automation create idempotency

Revision ID: 0005
Revises: 0004

Plan 9 補強：建立任務也接受冪等鍵。佔用鍵時任務還沒建立，所以 automation_requests.job_id 改為可空，
建立成功後補上新任務的 id。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0005'
down_revision: str | Sequence[str] | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column('automation_requests', 'job_id', existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    op.execute('DELETE FROM automation_requests WHERE job_id IS NULL')
    op.alter_column('automation_requests', 'job_id', existing_type=sa.String(), nullable=False)
