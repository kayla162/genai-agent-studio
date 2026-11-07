"""history.selected webhook

Revision ID: 0006
Revises: 0005

選圖後發布：選定海報時也寫 outbox（history.selected）。同一個任務可以選定多次，所以把 (job_id, event) 的唯一限制
改成只限制 job.finished（每個任務一則）的部分唯一索引。
"""

from collections.abc import Sequence

from alembic import op

revision: str = '0006'
down_revision: str | Sequence[str] | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint('uq_webhook_outbox_job_event', 'webhook_outbox', type_='unique')
    op.create_index(
        'uq_webhook_outbox_job_finished',
        'webhook_outbox',
        ['job_id'],
        unique=True,
        postgresql_where="event = 'job.finished'",
    )


def downgrade() -> None:
    # 舊的限制不允許同一個任務有多則同類事件：先刪掉 history.selected（已送出或還沒送出的定稿通知）
    op.execute("DELETE FROM webhook_outbox WHERE event <> 'job.finished'")
    op.drop_index('uq_webhook_outbox_job_finished', table_name='webhook_outbox')
    op.create_unique_constraint('uq_webhook_outbox_job_event', 'webhook_outbox', ['job_id', 'event'])
