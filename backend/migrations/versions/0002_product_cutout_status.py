"""product cutout status

Revision ID: 0002
Revises: 0001

去背改為真正的 BiRefNet：ProductCutout 加上 status 與 error。
上傳與本機匯入的商品（含模擬去背過的）一律改為 pending，worker 啟動時會重新排入去背。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0002'
down_revision: str | Sequence[str] | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE products
            SET data = jsonb_set(
                data, '{cutout}',
                '{"model": "BiRefNet-general", "status": "pending", "url": null, "error": null}'::jsonb
            )
            WHERE data->'photo'->>'source' IN ('upload', 'local')
              AND data->'cutout'->>'status' IS NULL
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE products
            SET data = jsonb_set(data, '{cutout}', (data->'cutout') - 'status' - 'error')
            WHERE jsonb_typeof(data->'cutout') = 'object'
            """
        )
    )
