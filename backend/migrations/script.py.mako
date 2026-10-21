<%doc>
  產生的 migration 要通過 ruff check、ruff format 與 mypy（strict）：不用 typing.Union，import 依序排列；
  op 與 sa 有用到才 import（空白的 migration 不留沒用到的 import）。
  autogenerate 產生的指令排版不符合 ruff format，由 alembic.ini 的 post_write_hooks 執行 ruff 修正。
</%doc>\
<%
    body = (upgrades or '') + (downgrades or '')
%>\
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from collections.abc import Sequence
% if 'sa.' in body or 'op.' in body:

% endif
% if 'sa.' in body:
import sqlalchemy as sa
% endif
% if 'op.' in body:
from alembic import op
% endif
% if imports:
${imports}
% endif

revision: str = ${repr(up_revision)}
down_revision: str | Sequence[str] | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
