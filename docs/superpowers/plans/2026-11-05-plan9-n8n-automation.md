# Plan 9：n8n 自動化整合 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 n8n 能以 token 呼叫自動化 API 建任務、核准與退回，並在任務結束時收到帶 HMAC 簽章、以 outbox 保證不漏送的 webhook；附上試算表批次產圖與 Discord 審核兩條工作流。

**Architecture:** `EventStore.append` 在寫入結束階段的同一個交易內插入 `webhook_outbox`；worker 的發送迴圈每 2 秒以 `FOR UPDATE SKIP LOCKED` 取到期的通知、簽章後 POST，失敗依退避表重試。`/api/automation/*` 以 Bearer token 驗證，內部重用既有的建任務與選圖函式；退回意見存在 `jobs` 資料表，由 runner 帶進 RAG 查詢、Gemini Prompt 與價格護欄。n8n 放在 compose 的 `automation` profile。

**Tech Stack:** FastAPI、SQLAlchemy 2（asyncpg）、alembic、httpx、respx、SAQ worker、pytest-asyncio；n8n（官方映像）、Google Sheets、Discord webhook。

**Spec:** `docs/superpowers/specs/2026-11-05-plan9-n8n-automation-design.md`（§12「撰寫實作計畫時的調整」優先於前面各節）

## Global Constraints

- 所有使用者看得到的訊息（錯誤、log、狀態說明、文件）一律繁體中文；程式碼註解沿用專案的繁體中文風格。
- 後端指令在 `backend/` 執行：測試 `uv run pytest`，型別 `uv run mypy app tests`，格式 `uv run ruff check . && uv run ruff format --check .`。資料庫測試需要 `docker compose up -d postgres redis chroma`。
- 新的環境變數名稱固定為：`AUTOMATION_TOKEN`、`JOB_WEBHOOK_URL`、`JOB_WEBHOOK_SECRET`、`STUDIO_BASE_URL`、`AUTOMATION_TEMPLATES`、`AUTOMATION_VARIANTS`。
- `AUTOMATION_TOKEN` 與 `JOB_WEBHOOK_SECRET` 至少 32 字元；空字串代表停用。
- 簽章：`X-Webhook-Signature: v1=<hex(HMAC-SHA256(secret, f"{timestamp}.".encode() + body))>`；`X-Webhook-Id`、`X-Webhook-Event`、`X-Webhook-Timestamp` 一起送。
- 退避表（第 n 次失敗後等待的秒數）：10、60、300、900、1800、3600、7200；第 8 次仍失敗 → `dead`。4xx（408、429 除外）直接 `dead`。
- 退回鏈最多 3 次（`MAX_REVISIONS = 3`），超過回 409。
- n8n 只綁 `127.0.0.1:5678`，以非 root 執行，在 `automation` profile；憑證不進 repo。
- 不改 `JobInput` 合約、`contracts/fixtures/` 與前端型別。
- 測試的 `Settings` 一律以 `_env_file=None` 建立。
- commit 訊息以英文 conventional commits 撰寫，結尾加 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。

## File Structure

| 檔案 | 動作 | 責任 |
|---|---|---|
| `backend/app/settings.py` | 修改 | 新設定與驗證 |
| `backend/app/errors.py` | 修改 | 新增 `Unauthorized`（401） |
| `backend/app/db/models.py` | 修改 | `JobRow` 三個欄位、`WebhookOutboxRow`、`AutomationRequestRow` |
| `backend/migrations/versions/0004_automation.py` | 新增 | 對應的 migration |
| `backend/app/webhooks/__init__.py` | 新增 | 空檔 |
| `backend/app/webhooks/payload.py` | 新增 | 由任務列與事件組出 `job.finished` payload、挑最佳候選（純函式） |
| `backend/app/webhooks/signing.py` | 新增 | body 編碼、簽章與標頭（純函式） |
| `backend/app/webhooks/delivery.py` | 新增 | 取到期通知、發送、套用結果、發送迴圈 |
| `backend/app/events.py` | 修改 | `WebhookTarget`、交易內寫 outbox |
| `backend/app/repo/jobs.py` | 修改 | `create_job` 接受三個欄位、`ancestor_count` |
| `backend/app/api/jobs.py` | 修改 | 抽出 `parse_text`、`submit_job`、`record_selection` |
| `backend/app/api/automation.py` | 新增 | token 驗證、三個自動化端點、冪等 |
| `backend/app/api/main.py` | 修改 | 掛上 automation router |
| `backend/app/api/services.py` | 修改 | 以 `webhook_target` 建立 `EventStore` |
| `backend/app/api/catalog.py` | 修改 | 系統狀態的「Webhook」元件 |
| `backend/app/worker.py` | 修改 | `EventStore` 帶 webhook、啟動發送迴圈 |
| `backend/app/pipeline/runner.py` | 修改 | 載入退回意見、log、傳給 RAG 與 Prompt 構建 |
| `backend/app/pipeline/ports.py` | 修改 | `SpecRequest.feedback` |
| `backend/app/pipeline/gemini.py` | 修改 | payload 加上 `reviewerFeedback` |
| `backend/app/pipeline/prompts/spec.md` | 修改 | 說明 `reviewerFeedback` |
| `backend/app/adapters/composer.py` | 修改 | 護欄的 `text` 併入意見 |
| `docker-compose.yml` | 修改 | `n8n-db`、`n8n` 服務、api 的 `ALLOWED_HOSTS` |
| `n8n/workflows/*.json` | 新增 | 三條工作流 |
| `n8n/README.md` | 新增 | 設定、啟動、憑證、更新工作流 |
| `.env.example` | 修改 | 新變數 |
| `backend/tests/test_webhook_payload.py`、`test_webhook_signing.py`、`test_webhook_outbox.py`、`test_webhook_delivery.py`、`test_api_automation.py`、`test_n8n_workflows.py`、`test_automation_live.py` | 新增 | 測試 |
| `README.md` | 修改 | 「自動化整合」一節 |

---

### Task 1：設定、錯誤類別與資料表

**Files:**
- Modify: `backend/app/settings.py`
- Modify: `backend/app/errors.py`
- Modify: `backend/app/db/models.py`
- Create: `backend/migrations/versions/0004_automation.py`
- Test: `backend/tests/test_settings.py`

**Interfaces:**
- Produces:
  - `Settings.automation_token: SecretStr`、`job_webhook_url: str`、`job_webhook_secret: SecretStr`、`studio_base_url: str`、`automation_templates: list[TemplateId]`、`automation_variants: int`
  - `app.errors.Unauthorized`（status 401、code `unauthorized`）
  - `JobRow.client_ref: str | None`、`JobRow.parent_job_id: str | None`、`JobRow.reviewer_feedback: str | None`
  - `WebhookOutboxRow`（`webhook_outbox`）：`id`、`job_id`、`event`、`payload`、`status`、`attempts`、`next_attempt_at`、`last_error`、`created_at`、`delivered_at`
  - `AutomationRequestRow`（`automation_requests`）：`key`、`action`、`job_id`、`response`、`created_at`

- [ ] **Step 1：寫失敗的測試**（加在 `backend/tests/test_settings.py` 最後）

```python
TOKEN = 't' * 32
SECRET = 's' * 32


def test_automation_defaults_are_off() -> None:
    s = Settings(_env_file=None)
    assert s.automation_token.get_secret_value() == ''
    assert s.job_webhook_url == ''
    assert s.job_webhook_secret.get_secret_value() == ''
    assert s.studio_base_url == 'http://127.0.0.1:3000'
    assert s.automation_templates == ['ig-post', 'story', 'ecom-main']
    assert s.automation_variants == 2
    assert TOKEN not in repr(Settings(_env_file=None, automation_token=TOKEN))


def test_automation_token_must_be_long_enough() -> None:
    with pytest.raises(ValidationError, match='AUTOMATION_TOKEN 至少要 32 個字元'):
        Settings(_env_file=None, automation_token='short')
    assert Settings(_env_file=None, automation_token=TOKEN).automation_token.get_secret_value() == TOKEN


def test_job_webhook_needs_an_http_url_and_a_secret() -> None:
    with pytest.raises(ValidationError, match='JOB_WEBHOOK_URL 只能是 http:// 或 https://'):
        Settings(_env_file=None, job_webhook_url='ftp://n8n/hook', job_webhook_secret=SECRET)
    with pytest.raises(ValidationError, match='JOB_WEBHOOK_SECRET 必填且至少 32 個字元'):
        Settings(_env_file=None, job_webhook_url='http://n8n:5678/webhook/x')
    ok = Settings(_env_file=None, job_webhook_url='http://n8n:5678/webhook/x', job_webhook_secret=SECRET)
    assert ok.job_webhook_url == 'http://n8n:5678/webhook/x'


def test_automation_variants_range() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, automation_variants=9)
```

- [ ] **Step 2：確認測試失敗**

Run: `uv run pytest tests/test_settings.py -v`
Expected: 4 個新測試 FAIL（`Settings` 沒有 `automation_token` 等屬性）

- [ ] **Step 3：實作設定**

`backend/app/settings.py`：匯入加上 `from app.contract import TemplateId`，在 `sim_force_all_fail` 之後加入：

```python
    #: n8n 等自動化呼叫端的 token（/api/automation/*，Authorization: Bearer）；空字串為停用（回 404）
    automation_token: SecretStr = SecretStr('')
    #: 任務結束時通知的網址（compose 內為 http://n8n:5678/webhook/poster-job-finished）；空字串為不通知
    job_webhook_url: str = ''
    #: webhook 的 HMAC-SHA256 金鑰；job_webhook_url 有設定時必填
    job_webhook_secret: SecretStr = SecretStr('')
    #: webhook 的 studioUrl：{studio_base_url}/agent?job={jobId}
    studio_base_url: str = 'http://127.0.0.1:3000'
    #: 自動化建任務沒有指定時使用的模板（JSON 陣列）
    automation_templates: list[TemplateId] = ['ig-post', 'story', 'ecom-main']
    #: 自動化建任務沒有指定時，每個模板的候選張數
    automation_variants: int = Field(default=2, ge=1, le=8)
```

在 `_comfyui_needs_the_composer` 之後加入：

```python
    @model_validator(mode='after')
    def _automation_secrets(self) -> Self:
        """token 與 webhook 金鑰太短時啟動失敗：api 與 worker 會在啟動時顯示原因。"""
        token = self.automation_token.get_secret_value()
        if token and len(token) < MIN_SECRET_LENGTH:
            raise ValueError(
                f'AUTOMATION_TOKEN 至少要 {MIN_SECRET_LENGTH} 個字元'
                '（可用 python -c "import secrets; print(secrets.token_urlsafe(32))" 產生）'
            )
        if self.job_webhook_url:
            if not self.job_webhook_url.startswith(('http://', 'https://')):
                raise ValueError('JOB_WEBHOOK_URL 只能是 http:// 或 https:// 開頭的網址')
            if len(self.job_webhook_secret.get_secret_value()) < MIN_SECRET_LENGTH:
                raise ValueError(f'JOB_WEBHOOK_URL 有設定時，JOB_WEBHOOK_SECRET 必填且至少 {MIN_SECRET_LENGTH} 個字元')
        return self
```

並在 `BACKEND_DIR` 之後加上 `MIN_SECRET_LENGTH = 32`。

- [ ] **Step 4：確認設定的測試通過**

Run: `uv run pytest tests/test_settings.py -v`
Expected: PASS

- [ ] **Step 5：錯誤類別**

`backend/app/errors.py` 在 `NotFound` 之後加入：

```python
class Unauthorized(AppError):
    status = 401
    code = 'unauthorized'
```

- [ ] **Step 6：資料表模型**

`backend/app/db/models.py`：匯入加上 `Index`、`UniqueConstraint`（`from sqlalchemy import ...`）。`JobRow` 的 `failure_reason` 之後加入：

```python
    #: 自動化呼叫端的參照（例如 sheet:<id>:row:12）；原樣存起來，在 webhook 帶回
    client_ref: Mapped[str | None] = mapped_column(String)
    #: 由「退回並重新生成」建立時，被退回的任務
    parent_job_id: Mapped[str | None] = mapped_column(ForeignKey('jobs.id', ondelete='SET NULL'))
    #: 審核者的修改意見（Prompt 構建、RAG 查詢與價格護欄使用）
    reviewer_feedback: Mapped[str | None] = mapped_column(Text)
```

檔案最後加入：

```python
class WebhookOutboxRow(Base):
    """任務結束的通知：與結束事件在同一個交易內寫入，worker 發送並重試。payload 在寫入時就固定。"""

    __tablename__ = 'webhook_outbox'
    __table_args__ = (
        UniqueConstraint('job_id', 'event', name='uq_webhook_outbox_job_event'),
        Index('ix_webhook_outbox_due', 'status', 'next_attempt_at'),
    )

    #: wh_<12 位 hex>，也是 X-Webhook-Id（重送時不變）
    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey('jobs.id', ondelete='CASCADE'))
    #: job.finished
    event: Mapped[str]
    payload: Mapped[Json]
    #: pending、delivered、dead
    status: Mapped[str]
    attempts: Mapped[int] = mapped_column(Integer, server_default='0')
    next_attempt_at: Mapped[datetime]
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime]
    delivered_at: Mapped[datetime | None]


class AutomationRequestRow(Base):
    """自動化 API 的冪等鍵：同一個 (key, action) 再次呼叫時回傳第一次的回應。response 為空表示還在處理中。"""

    __tablename__ = 'automation_requests'

    key: Mapped[str] = mapped_column(String, primary_key=True)
    #: approve、revise
    action: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str]
    response: Mapped[Json | None]
    created_at: Mapped[datetime] = mapped_column(index=True)
```

- [ ] **Step 7：migration**

`backend/migrations/versions/0004_automation.py`：

```python
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
    op.create_foreign_key(
        'fk_jobs_parent_job_id', 'jobs', 'jobs', ['parent_job_id'], ['id'], ondelete='SET NULL'
    )
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
    op.create_index(
        op.f('ix_automation_requests_created_at'), 'automation_requests', ['created_at'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_automation_requests_created_at'), table_name='automation_requests')
    op.drop_table('automation_requests')
    op.drop_index('ix_webhook_outbox_due', table_name='webhook_outbox')
    op.drop_table('webhook_outbox')
    op.drop_constraint('fk_jobs_parent_job_id', 'jobs', type_='foreignkey')
    op.drop_column('jobs', 'reviewer_feedback')
    op.drop_column('jobs', 'parent_job_id')
    op.drop_column('jobs', 'client_ref')
```

- [ ] **Step 8：確認 migration 與模型一致、整套測試仍通過**

Run: `uv run pytest tests/test_settings.py tests/test_jobs.py tests/test_events.py -v`
Expected: PASS（conftest 會重建 `genai_test` 並跑到 0004；`truncate_all` 依 `Base.metadata` 一併清空新資料表）

Run: `uv run alembic check`（設定 `DATABASE_URL` 指向本機 compose 的 postgres：`postgresql+asyncpg://genai:genai@127.0.0.1:5433/genai`，先 `uv run alembic upgrade head`）
Expected: `No new upgrade operations detected.`

- [ ] **Step 9：Commit**

```bash
git add backend/app/settings.py backend/app/errors.py backend/app/db/models.py backend/migrations/versions/0004_automation.py backend/tests/test_settings.py
git commit -m "feat: add automation settings, outbox and idempotency tables"
```

---

### Task 2：webhook payload 與簽章（純函式）

**Files:**
- Create: `backend/app/webhooks/__init__.py`（空檔）
- Create: `backend/app/webhooks/payload.py`
- Create: `backend/app/webhooks/signing.py`
- Test: `backend/tests/test_webhook_payload.py`
- Test: `backend/tests/test_webhook_signing.py`

**Interfaces:**
- Produces:
  - `payload.EVENT = 'job.finished'`
  - `payload.Candidate`（TypedDict）：`renderId`、`templateId`、`round`、`variant`、`score`、`passed`、`imageUrl`
  - `payload.candidates(best_render_ids: Mapping[str, str], events: Iterable[Mapping[str, Any]]) -> list[Candidate]`：每個模板一張（`best_render_ids` 指定的優先，其次為分數最高、同分取較晚的一輪），依 `TEMPLATE_IDS` 排序
  - `payload.best(candidates: list[Candidate]) -> Candidate | None`：分數最高者
  - `payload.studio_url(base: str, job_id: str) -> str`
  - `payload.build_job_finished(*, webhook_id: str, job_id: str, stage: str, round: int, job_input: Mapping[str, Any], client_ref: str | None, parent_job_id: str | None, best_render_ids: Mapping[str, str], events: Sequence[Mapping[str, Any]], studio_base_url: str, finished_at: str) -> dict[str, Any]`
  - `signing.encode(payload: Mapping[str, Any]) -> bytes`
  - `signing.sign(secret: str, timestamp: int, body: bytes) -> str`（回傳 `v1=<hex>`）
  - `signing.headers(*, webhook_id: str, event: str, secret: str, timestamp: int, body: bytes) -> dict[str, str]`

- [ ] **Step 1：寫簽章的失敗測試** `backend/tests/test_webhook_signing.py`

```python
"""webhook 的 body 編碼與 HMAC 簽章：golden 值以 Python 的 hmac 另外算出。"""

from app.webhooks.signing import encode, headers, sign

SECRET = 's' * 32
TS = 1793865600
BODY = b'{"event":"job.finished","jobId":"job_x"}'
GOLDEN = 'v1=da6062c9083af0871bd5b0210dbf666128432245739944acb0a12a0fdeb11501'


def test_encode_is_compact_utf8_and_keeps_key_order() -> None:
    assert encode({'event': 'job.finished', 'jobId': 'job_x'}) == BODY
    assert encode({'brief': '週年慶'}) == '{"brief":"週年慶"}'.encode()


def test_sign_matches_the_golden_value() -> None:
    assert sign(SECRET, TS, BODY) == GOLDEN
    assert sign(SECRET, TS + 1, BODY) != GOLDEN
    assert sign('x' * 32, TS, BODY) != GOLDEN


def test_headers() -> None:
    assert headers(webhook_id='wh_1', event='job.finished', secret=SECRET, timestamp=TS, body=BODY) == {
        'Content-Type': 'application/json; charset=utf-8',
        'User-Agent': 'genai-agent-webhook/1',
        'X-Webhook-Id': 'wh_1',
        'X-Webhook-Event': 'job.finished',
        'X-Webhook-Timestamp': str(TS),
        'X-Webhook-Signature': GOLDEN,
    }
```

- [ ] **Step 2：確認失敗**

Run: `uv run pytest tests/test_webhook_signing.py -v`
Expected: FAIL（`ModuleNotFoundError: app.webhooks`）

- [ ] **Step 3：實作** `backend/app/webhooks/signing.py`

```python
"""webhook 的 body 與簽章：簽的是實際送出的位元組（timestamp + "." + body），接收端要用原始 body 驗證。"""

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any


def encode(payload: Mapping[str, Any]) -> bytes:
    """緊湊的 UTF-8 JSON（不轉義中文），依原本的鍵順序。"""
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()


def sign(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f'{timestamp}.'.encode() + body, hashlib.sha256)
    return f'v1={mac.hexdigest()}'


def headers(*, webhook_id: str, event: str, secret: str, timestamp: int, body: bytes) -> dict[str, str]:
    return {
        'Content-Type': 'application/json; charset=utf-8',
        'User-Agent': 'genai-agent-webhook/1',
        'X-Webhook-Id': webhook_id,
        'X-Webhook-Event': event,
        'X-Webhook-Timestamp': str(timestamp),
        'X-Webhook-Signature': sign(secret, timestamp, body),
    }
```

並建立空的 `backend/app/webhooks/__init__.py`。

- [ ] **Step 4：確認通過**

Run: `uv run pytest tests/test_webhook_signing.py -v`
Expected: PASS

- [ ] **Step 5：寫 payload 的失敗測試** `backend/tests/test_webhook_payload.py`

```python
"""job.finished payload：每個模板挑一張、最佳候選、未通過的檢查、失敗原因與 studioUrl。"""

from typing import Any

from app.webhooks.payload import EVENT, best, build_job_finished, candidates, studio_url

INPUT = {'brandId': 'selune', 'productId': 'prod_selune_serum', 'brief': '週年慶買一送一'}


def render(id_: str, template: str, round_: int, variant: int = 0) -> dict[str, Any]:
    return {'id': id_, 'templateId': template, 'round': round_, 'variant': variant}


def check(id_: str, status: str) -> dict[str, Any]:
    return {'id': id_, 'name': f'檢查 {id_}', 'kind': 'rule', 'rule': 'r', 'value': 'v', 'status': status,
            'target': None, 'ragRef': None}


EVENTS: list[dict[str, Any]] = [
    {'type': 'render.completed', 'round': 1, 'renders': [render('r1', 'story', 1), render('r2', 'ig-post', 1)]},
    {'type': 'review.check', 'round': 1, 'renderId': 'r1', 'check': check('banned_words', 'fail')},
    {'type': 'review.completed', 'round': 1, 'renderId': 'r1', 'score': 60, 'passed': False, 'image': '/files/jobs/j/r1.png'},
    {'type': 'review.completed', 'round': 1, 'renderId': 'r2', 'score': 92, 'passed': True, 'image': '/files/jobs/j/r2.png'},
    {'type': 'render.completed', 'round': 2, 'renders': [render('r3', 'story', 2)]},
    {'type': 'review.check', 'round': 2, 'renderId': 'r3', 'check': check('whitespace', 'warn')},
    {'type': 'review.check', 'round': 2, 'renderId': 'r3', 'check': check('contrast', 'pass')},
    {'type': 'review.completed', 'round': 2, 'renderId': 'r3', 'score': 95, 'passed': True, 'image': '/files/jobs/j/r3.png'},
]


def test_candidates_pick_one_per_template_in_template_order() -> None:
    picked = candidates({}, EVENTS)
    assert [c['renderId'] for c in picked] == ['r2', 'r3']  # ig-post 在 story 之前（TEMPLATE_IDS 的順序）
    assert picked[1] == {'renderId': 'r3', 'templateId': 'story', 'round': 2, 'variant': 0, 'score': 95,
                         'passed': True, 'imageUrl': '/files/jobs/j/r3.png'}


def test_best_render_ids_win_over_scores() -> None:
    picked = candidates({'story': 'r1'}, EVENTS)
    assert [c['renderId'] for c in picked] == ['r2', 'r1']


def test_unreviewed_renders_are_skipped_and_best_is_the_highest_score() -> None:
    events = [{'type': 'render.completed', 'round': 1, 'renders': [render('r9', 'banner', 1)]}, *EVENTS]
    picked = candidates({}, events)
    assert 'r9' not in [c['renderId'] for c in picked]
    top = best(picked)
    assert top is not None and top['renderId'] == 'r3'
    assert best([]) is None


def test_studio_url() -> None:
    assert studio_url('http://127.0.0.1:3000/', 'job_1') == 'http://127.0.0.1:3000/agent?job=job_1'


def test_build_job_finished_for_a_done_job() -> None:
    data = build_job_finished(
        webhook_id='wh_1', job_id='job_1', stage='done', round=2, job_input=INPUT, client_ref='sheet:x:row:3',
        parent_job_id=None, best_render_ids={}, events=EVENTS, studio_base_url='http://127.0.0.1:3000',
        finished_at='2026-11-05T10:00:00+08:00',
    )
    assert data['event'] == EVENT
    assert (data['webhookId'], data['jobId'], data['clientRef'], data['stage'], data['round']) == (
        'wh_1', 'job_1', 'sheet:x:row:3', 'done', 2)
    assert (data['brandId'], data['productId'], data['brief']) == ('selune', 'prod_selune_serum', '週年慶買一送一')
    assert data['best']['renderId'] == 'r3'
    assert [r['renderId'] for r in data['renders']] == ['r2', 'r3']
    assert data['failedChecks'] == [{'id': 'whitespace', 'name': '檢查 whitespace', 'status': 'warn', 'value': 'v'}]
    assert data['reason'] is None
    assert data['studioUrl'] == 'http://127.0.0.1:3000/agent?job=job_1'
    assert data['finishedAt'] == '2026-11-05T10:00:00+08:00'
    assert list(data) == ['event', 'webhookId', 'jobId', 'clientRef', 'parentJobId', 'stage', 'round', 'brandId',
                          'productId', 'brief', 'best', 'renders', 'failedChecks', 'reason', 'studioUrl', 'finishedAt']


def test_build_job_finished_for_failed_and_needs_review_jobs() -> None:
    common: dict[str, Any] = {'webhook_id': 'wh_2', 'job_id': 'job_2', 'round': 1, 'job_input': INPUT,
                              'client_ref': None, 'parent_job_id': 'job_1', 'best_render_ids': {},
                              'studio_base_url': 'http://h', 'finished_at': 't'}
    failed = build_job_finished(stage='failed', events=[{'type': 'job.failed', 'jobId': 'job_2', 'reason': 'composer 沒有回應'}], **common)
    assert (failed['best'], failed['renders'], failed['failedChecks']) == (None, [], [])
    assert (failed['reason'], failed['parentJobId']) == ('composer 沒有回應', 'job_1')
    review = build_job_finished(stage='needs_review', events=[*EVENTS, {'type': 'job.needs_review', 'jobId': 'job_2', 'reason': '已達最大重試次數'}], **common)
    assert review['best']['renderId'] == 'r3'
    assert review['reason'] == '已達最大重試次數'
```

- [ ] **Step 6：確認失敗**

Run: `uv run pytest tests/test_webhook_payload.py -v`
Expected: FAIL（`ModuleNotFoundError: app.webhooks.payload`）

- [ ] **Step 7：實作** `backend/app/webhooks/payload.py`

```python
"""job.finished 的內容：由任務列的欄位與任務的全部事件（payload，不含 seq、ts）組成。

每個模板挑一張候選：job.completed 指定的最佳候選優先，其次為已審查的候選中分數最高者（同分取較晚的一輪）。
needs_review 沒有 job.completed，所以一樣依分數挑選；failed、cancelled 通常沒有候選，best 為 None。
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, TypedDict

from app.contract import TEMPLATE_IDS

EVENT = 'job.finished'


class Candidate(TypedDict):
    renderId: str
    templateId: str
    round: int
    variant: int
    score: int | None
    passed: bool | None
    #: 伺服器端繪製的審查用海報（/files/...）；REVIEW_MODE=sim 時為 None
    imageUrl: str | None


def _collect(events: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Candidate], dict[str, list[dict[str, Any]]]]:
    found: dict[str, Candidate] = {}
    checks: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        if e['type'] == 'render.completed':
            for r in e['renders']:
                found[r['id']] = Candidate(
                    renderId=r['id'], templateId=r['templateId'], round=r['round'], variant=r['variant'],
                    score=None, passed=None, imageUrl=None,
                )
                checks[r['id']] = []
        elif e['type'] == 'review.check' and e['renderId'] in found:
            checks[e['renderId']].append(e['check'])
        elif e['type'] == 'review.completed' and e['renderId'] in found:
            c = found[e['renderId']]
            c['score'], c['passed'], c['imageUrl'] = e['score'], e['passed'], e.get('image')
    return found, checks


def candidates(best_render_ids: Mapping[str, str], events: Iterable[Mapping[str, Any]]) -> list[Candidate]:
    found, _ = _collect(events)
    by_template: dict[str, Candidate] = {}
    for c in found.values():
        if c['score'] is None:
            continue
        current = by_template.get(c['templateId'])
        if current is None or (c['score'], c['round']) >= (current['score'] or 0, current['round']):
            by_template[c['templateId']] = c
    for template, render_id in best_render_ids.items():
        if render_id in found:
            by_template[template] = found[render_id]
    return [by_template[t] for t in TEMPLATE_IDS if t in by_template]


def best(picked: list[Candidate]) -> Candidate | None:
    return max(picked, key=lambda c: c['score'] or 0, default=None)


def studio_url(base: str, job_id: str) -> str:
    return f'{base.rstrip("/")}/agent?job={job_id}'


def _reason(events: Sequence[Mapping[str, Any]]) -> str | None:
    for e in reversed(events):
        if e['type'] in ('job.failed', 'job.needs_review'):
            return str(e['reason'])
    return None


def build_job_finished(
    *,
    webhook_id: str,
    job_id: str,
    stage: str,
    round: int,
    job_input: Mapping[str, Any],
    client_ref: str | None,
    parent_job_id: str | None,
    best_render_ids: Mapping[str, str],
    events: Sequence[Mapping[str, Any]],
    studio_base_url: str,
    finished_at: str,
) -> dict[str, Any]:
    picked = candidates(best_render_ids, events)
    top = best(picked)
    _, checks = _collect(events)
    failed = [
        {'id': c['id'], 'name': c['name'], 'status': c['status'], 'value': c['value']}
        for c in (checks.get(top['renderId'], []) if top else [])
        if c['status'] != 'pass'
    ]
    return {
        'event': EVENT,
        'webhookId': webhook_id,
        'jobId': job_id,
        'clientRef': client_ref,
        'parentJobId': parent_job_id,
        'stage': stage,
        'round': round,
        'brandId': job_input['brandId'],
        'productId': job_input['productId'],
        'brief': job_input['brief'],
        'best': top,
        'renders': picked,
        'failedChecks': failed,
        'reason': _reason(events),
        'studioUrl': studio_url(studio_base_url, job_id),
        'finishedAt': finished_at,
    }
```

- [ ] **Step 8：確認通過，跑型別與格式**

Run: `uv run pytest tests/test_webhook_payload.py tests/test_webhook_signing.py -v && uv run mypy app tests && uv run ruff check . && uv run ruff format --check .`
Expected: PASS；mypy、ruff 沒有錯誤（ruff format 有差異時執行 `uv run ruff format .` 後再檢查）

- [ ] **Step 9：Commit**

```bash
git add backend/app/webhooks backend/tests/test_webhook_payload.py backend/tests/test_webhook_signing.py
git commit -m "feat: build and sign the job.finished webhook payload"
```

---

### Task 3：交易內寫入 outbox

**Files:**
- Modify: `backend/app/events.py`
- Modify: `backend/app/api/services.py`
- Modify: `backend/app/worker.py`（只改 `build_services`）
- Test: `backend/tests/test_webhook_outbox.py`

**Interfaces:**
- Consumes: `payload.build_job_finished`、`payload.EVENT`（Task 2）；`WebhookOutboxRow`、`JobRow.client_ref`、`JobRow.parent_job_id`（Task 1）
- Produces:
  - `events.WebhookTarget(studio_base_url: str)`（frozen dataclass）
  - `events.webhook_target(settings: Settings) -> WebhookTarget | None`：`job_webhook_url` 為空時回傳 None
  - `EventStore(db, redis, webhook: WebhookTarget | None = None)`
  - `events.new_webhook_id() -> str`（`wh_` ＋ 12 位 hex）

- [ ] **Step 1：寫失敗的測試** `backend/tests/test_webhook_outbox.py`

```python
"""結束階段的 job.status 與 outbox 在同一個交易內寫入；沒有設定 webhook 時不寫。"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.contract import JobFailedEvent, JobStatusEvent
from app.db.models import JobEventRow, WebhookOutboxRow
from app.db.session import Database
from app.events import EventStore, WebhookTarget, webhook_target
from app.repo import jobs
from app.settings import Settings
from tests.test_jobs import job_input

NOW = datetime(2026, 11, 5, 2, 0, tzinfo=UTC)
TARGET = WebhookTarget(studio_base_url='http://127.0.0.1:3000')


def status(stage: str, round_: int = 1) -> JobStatusEvent:
    return JobStatusEvent.model_validate({'type': 'job.status', 'stage': stage, 'round': round_})


@pytest.fixture
async def job(db: Database) -> AsyncIterator[str]:
    async with db.session() as s:
        await jobs.create_job(s, 'job_w', job_input(), NOW, client_ref='sheet:abc:row:2')
    yield 'job_w'
    await db.truncate_all()


async def outbox(db: Database) -> list[WebhookOutboxRow]:
    async with db.session() as s:
        return list(await s.scalars(select(WebhookOutboxRow)))


def test_webhook_target_follows_the_settings() -> None:
    assert webhook_target(Settings(_env_file=None)) is None
    configured = Settings(_env_file=None, job_webhook_url='http://n8n:5678/webhook/x', job_webhook_secret='s' * 32,
                          studio_base_url='http://studio')
    assert webhook_target(configured) == WebhookTarget(studio_base_url='http://studio')


async def test_only_the_finishing_status_writes_one_outbox_row(db: Database, redis: Redis, job: str) -> None:
    store = EventStore(db, redis, TARGET)
    await store.append(job, status('parsing', 0))
    await store.append(job, status('reviewing'))
    assert await outbox(db) == []
    await store.append(job, JobFailedEvent(type='job.failed', job_id=job, reason='composer 沒有回應'))
    await store.append(job, status('failed'))
    [row] = await outbox(db)
    assert row.id.startswith('wh_') and len(row.id) == 15
    assert (row.job_id, row.event, row.status, row.attempts, row.last_error) == (job, 'job.finished', 'pending', 0, None)
    assert row.next_attempt_at == row.created_at
    assert row.payload['webhookId'] == row.id
    assert (row.payload['stage'], row.payload['clientRef'], row.payload['reason']) == ('failed', 'sheet:abc:row:2', 'composer 沒有回應')
    assert row.payload['studioUrl'] == f'http://127.0.0.1:3000/agent?job={job}'


async def test_a_second_finishing_status_does_not_add_a_row_or_fail(db: Database, redis: Redis, job: str) -> None:
    store = EventStore(db, redis, TARGET)
    await store.append(job, status('cancelled'))
    assert await store.append(job, status('failed')) is not None
    assert len(await outbox(db)) == 1


async def test_no_outbox_without_a_webhook(db: Database, redis: Redis, job: str) -> None:
    await EventStore(db, redis).append(job, status('done'))
    assert await outbox(db) == []


async def test_expect_stage_mismatch_writes_neither_event_nor_outbox(db: Database, redis: Redis, job: str) -> None:
    store = EventStore(db, redis, TARGET)
    await store.append(job, status('parsing', 0))
    assert await store.append(job, status('cancelled', 0), expect_stage='queued') is None
    assert await outbox(db) == []
    async with db.session() as s:
        assert [e.type for e in await s.scalars(select(JobEventRow).where(JobEventRow.job_id == job))] == ['job.status']
```

- [ ] **Step 2：確認失敗**

Run: `uv run pytest tests/test_webhook_outbox.py -v`
Expected: FAIL（`ImportError: cannot import name 'WebhookTarget'`；`create_job` 也還不接受 `client_ref`）

- [ ] **Step 3：讓 `repo.jobs.create_job` 接受自動化欄位**

`backend/app/repo/jobs.py` 的 `create_job` 改為：

```python
async def create_job(
    session: AsyncSession,
    job_id: str,
    job_input: JobInput,
    now: datetime,
    *,
    client_ref: str | None = None,
    parent_job_id: str | None = None,
    reviewer_feedback: str | None = None,
) -> None:
    session.add(
        JobRow(
            id=job_id,
            brand_id=job_input.brand_id,
            input=job_input.to_json(),
            created_at=now,
            stage='queued',
            client_ref=client_ref,
            parent_job_id=parent_job_id,
            reviewer_feedback=reviewer_feedback,
        )
    )
    await session.commit()
```

- [ ] **Step 4：實作 outbox 寫入** `backend/app/events.py`

匯入加上：

```python
import secrets
from dataclasses import dataclass

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WebhookOutboxRow
from app.settings import Settings
from app.webhooks.payload import EVENT as WEBHOOK_EVENT
from app.webhooks.payload import build_job_finished
```

在 `channel` 之前加入：

```python
@dataclass(frozen=True)
class WebhookTarget:
    """任務結束時要寫 outbox（JOB_WEBHOOK_URL 有設定）。網址與金鑰在發送時才讀，不存進 outbox。"""

    studio_base_url: str


def webhook_target(settings: Settings) -> WebhookTarget | None:
    return WebhookTarget(settings.studio_base_url) if settings.job_webhook_url else None


def new_webhook_id() -> str:
    return f'wh_{secrets.token_hex(6)}'
```

`EventStore.__init__` 改為：

```python
    def __init__(self, db: Database, redis: Redis, webhook: WebhookTarget | None = None) -> None:
        self.db = db
        self.redis = redis
        self.webhook = webhook
```

`append` 在 `s.add(JobEventRow(...))` 與 `await s.commit()` 之間加入：

```python
            if self.webhook is not None and event.type == 'job.status' and event.stage in FINISHED_STAGES:
                await self._add_outbox(s, row, iso(ts), ts)
```

並新增方法：

```python
    async def _add_outbox(self, s: AsyncSession, row: JobRow, finished_at: str, ts: datetime) -> None:
        """與結束事件同一個交易：任務結束與「待通知」一起成立。同一個任務已經有通知時不再新增（不讓事件寫入失敗）。"""
        assert self.webhook is not None
        await s.flush()
        events = list(
            await s.scalars(select(JobEventRow.payload).where(JobEventRow.job_id == row.id).order_by(JobEventRow.seq))
        )
        webhook_id = new_webhook_id()
        payload = build_job_finished(
            webhook_id=webhook_id,
            job_id=row.id,
            stage=row.stage,
            round=row.round,
            job_input=row.input,
            client_ref=row.client_ref,
            parent_job_id=row.parent_job_id,
            best_render_ids=row.best_render_ids,
            events=events,
            studio_base_url=self.webhook.studio_base_url,
            finished_at=finished_at,
        )
        await s.execute(
            pg_insert(WebhookOutboxRow)
            .values(
                id=webhook_id, job_id=row.id, event=WEBHOOK_EVENT, payload=payload, status='pending',
                attempts=0, next_attempt_at=ts, created_at=ts,
            )
            .on_conflict_do_nothing(index_elements=['job_id', 'event'])
        )
```

（`datetime` 由 `from datetime import datetime` 匯入。）`finished_at` 用 UTC 的 `iso(ts)`，與既有事件的 `ts` 格式一致。

- [ ] **Step 5：確認通過**

Run: `uv run pytest tests/test_webhook_outbox.py tests/test_events.py -v`
Expected: PASS

- [ ] **Step 6：api 與 worker 建立 EventStore 時帶入 webhook**

`backend/app/api/services.py`：`from app.events import EventStore, webhook_target`，`start_services` 內的 `EventStore(db, redis)` 改為 `EventStore(db, redis, webhook_target(settings))`。

`backend/app/worker.py` 的 `build_services`：`store = EventStore(db, redis)` 改為 `store = EventStore(db, redis, webhook_target(settings))`，匯入改為 `from app.events import EventStore, webhook_target`。

- [ ] **Step 7：整套後端測試、型別與格式**

Run: `uv run pytest && uv run mypy app tests && uv run ruff check . && uv run ruff format --check .`
Expected: 全部 PASS

- [ ] **Step 8：Commit**

```bash
git add backend/app/events.py backend/app/repo/jobs.py backend/app/api/services.py backend/app/worker.py backend/tests/test_webhook_outbox.py
git commit -m "feat: write the job.finished outbox row in the finishing transaction"
```

---

### Task 4：發送與重試

**Files:**
- Create: `backend/app/webhooks/delivery.py`
- Modify: `backend/app/worker.py`（`main`）
- Test: `backend/tests/test_webhook_delivery.py`

**Interfaces:**
- Consumes: `signing.encode`、`signing.headers`（Task 2）；`WebhookOutboxRow`（Task 1）
- Produces:
  - `delivery.BACKOFF: tuple[int, ...] = (10, 60, 300, 900, 1800, 3600, 7200)`、`MAX_ATTEMPTS = 8`、`POLL_INTERVAL = 2.0`、`BATCH = 20`、`TIMEOUT = 10.0`
  - `delivery.Outcome(delivered: bool, retry: bool, error: str | None)`
  - `async def send(http: httpx.AsyncClient, settings: Settings, row: WebhookOutboxRow, now: datetime) -> Outcome`
  - `def apply_outcome(row: WebhookOutboxRow, outcome: Outcome, now: datetime) -> None`
  - `async def deliver_due(db: Database, settings: Settings, http: httpx.AsyncClient, now: datetime) -> int`（回傳送達筆數）
  - `async def deliver_periodically(db: Database, settings: Settings, interval: float = POLL_INTERVAL) -> None`

- [ ] **Step 1：寫失敗的測試** `backend/tests/test_webhook_delivery.py`

```python
"""發送：2xx 送達、4xx 直接 dead、5xx／408／429／連線錯誤依退避表重試、第 8 次 dead；只取到期的 pending。"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import select

from app.db.models import WebhookOutboxRow
from app.db.session import Database
from app.repo import jobs
from app.settings import Settings
from app.webhooks.delivery import BACKOFF, MAX_ATTEMPTS, Outcome, apply_outcome, deliver_due
from app.webhooks.signing import encode, sign
from tests.test_jobs import job_input

URL = 'http://n8n.test/webhook/poster-job-finished'
SECRET = 's' * 32
NOW = datetime(2026, 11, 5, 2, 0, tzinfo=UTC)
SETTINGS = Settings(_env_file=None, image_mode='sim', agent_mode='sim', job_webhook_url=URL, job_webhook_secret=SECRET)


def outbox_row(id_: str, *, status: str = 'pending', attempts: int = 0, due: datetime = NOW) -> WebhookOutboxRow:
    return WebhookOutboxRow(
        id=id_, job_id='job_d', event='job.finished', payload={'event': 'job.finished', 'webhookId': id_},
        status=status, attempts=attempts, next_attempt_at=due, created_at=NOW,
    )


@pytest.fixture
async def seeded(db: Database) -> AsyncIterator[Database]:
    async with db.session() as s:
        await jobs.create_job(s, 'job_d', job_input(), NOW)
    yield db
    await db.truncate_all()


async def add(db: Database, *rows: WebhookOutboxRow) -> None:
    async with db.session() as s:
        s.add_all(rows)
        await s.commit()


async def get(db: Database, id_: str) -> WebhookOutboxRow:
    async with db.session() as s:
        row = await s.get(WebhookOutboxRow, id_)
        assert row is not None
        return row


def test_apply_outcome_follows_the_backoff_table() -> None:
    row = outbox_row('wh_a')
    for n, wait in enumerate(BACKOFF, start=1):
        apply_outcome(row, Outcome(False, True, 'HTTP 503'), NOW)
        assert (row.status, row.attempts, row.next_attempt_at) == ('pending', n, NOW + timedelta(seconds=wait))
    apply_outcome(row, Outcome(False, True, 'HTTP 503'), NOW)
    assert (row.status, row.attempts, row.last_error) == ('dead', MAX_ATTEMPTS, 'HTTP 503')


def test_apply_outcome_delivered_and_permanent_failure() -> None:
    ok = outbox_row('wh_b', attempts=2)
    ok.last_error = 'HTTP 503'
    apply_outcome(ok, Outcome(True, False, None), NOW)
    assert (ok.status, ok.attempts, ok.delivered_at, ok.last_error) == ('delivered', 3, NOW, None)
    bad = outbox_row('wh_c')
    apply_outcome(bad, Outcome(False, False, 'HTTP 401：bad signature'), NOW)
    assert (bad.status, bad.attempts, bad.last_error) == ('dead', 1, 'HTTP 401：bad signature')


@respx.mock
async def test_deliver_due_sends_signed_body_and_records_results(seeded: Database) -> None:
    await add(seeded, outbox_row('wh_ok'), outbox_row('wh_4xx'), outbox_row('wh_5xx'), outbox_row('wh_429'),
              outbox_row('wh_later', due=NOW + timedelta(seconds=1)), outbox_row('wh_dead', status='dead'))
    codes = {'wh_ok': 204, 'wh_4xx': 401, 'wh_5xx': 502, 'wh_429': 429}
    route = respx.post(URL).mock(side_effect=lambda r: httpx.Response(codes[r.headers['X-Webhook-Id']], text='nope'))
    async with httpx.AsyncClient() as http:
        assert await deliver_due(seeded, SETTINGS, http, NOW) == 1
    assert route.call_count == 4
    sent = next(c.request for c in route.calls if c.request.headers['X-Webhook-Id'] == 'wh_ok')
    body = encode({'event': 'job.finished', 'webhookId': 'wh_ok'})
    assert sent.content == body
    ts = int(sent.headers['X-Webhook-Timestamp'])
    assert ts == int(NOW.timestamp())
    assert sent.headers['X-Webhook-Signature'] == sign(SECRET, ts, body)
    assert (await get(seeded, 'wh_ok')).status == 'delivered'
    assert (await get(seeded, 'wh_4xx')).status == 'dead'
    assert (await get(seeded, 'wh_4xx')).last_error == 'HTTP 401：nope'
    for retried in ('wh_5xx', 'wh_429'):
        row = await get(seeded, retried)
        assert (row.status, row.attempts, row.next_attempt_at) == ('pending', 1, NOW + timedelta(seconds=BACKOFF[0]))
    assert (await get(seeded, 'wh_later')).attempts == 0


@respx.mock
async def test_connection_errors_are_retried(seeded: Database) -> None:
    await add(seeded, outbox_row('wh_x'))
    respx.post(URL).mock(side_effect=httpx.ConnectError('connection refused'))
    async with httpx.AsyncClient() as http:
        assert await deliver_due(seeded, SETTINGS, http, NOW) == 0
    row = await get(seeded, 'wh_x')
    assert (row.status, row.attempts) == ('pending', 1)
    assert row.last_error is not None and row.last_error.startswith('連線失敗')


@respx.mock
async def test_concurrent_deliveries_do_not_send_the_same_row_twice(seeded: Database) -> None:
    await add(seeded, *(outbox_row(f'wh_{i}') for i in range(5)))

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.2)
        return httpx.Response(200)

    route = respx.post(URL).mock(side_effect=slow)
    async with httpx.AsyncClient() as http:
        counts = await asyncio.gather(*(deliver_due(seeded, SETTINGS, http, NOW) for _ in range(3)))
    assert sum(counts) == 5
    assert route.call_count == 5


async def test_nothing_happens_without_a_webhook_url(seeded: Database) -> None:
    await add(seeded, outbox_row('wh_off'))
    async with httpx.AsyncClient() as http:
        assert await deliver_due(seeded, Settings(_env_file=None, image_mode='sim', agent_mode='sim'), http, NOW) == 0
    async with seeded.session() as s:
        assert [r.attempts for r in await s.scalars(select(WebhookOutboxRow))] == [0]
```

- [ ] **Step 2：確認失敗**

Run: `uv run pytest tests/test_webhook_delivery.py -v`
Expected: FAIL（`ModuleNotFoundError: app.webhooks.delivery`）

- [ ] **Step 3：實作** `backend/app/webhooks/delivery.py`

```python
"""發送任務結束的通知：worker 每 POLL_INTERVAL 秒取一批到期的 pending（FOR UPDATE SKIP LOCKED，不會重複取得），
簽章後 POST，依結果標記送達、排定重試或放棄（dead）。接收端依 X-Webhook-Id 去重：worker 在送出後、寫入結果前
被結束時，同一則通知會再送一次。"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select

from app.core.clock import utc_now
from app.db.models import WebhookOutboxRow
from app.db.session import Database
from app.settings import Settings
from app.webhooks.signing import encode, headers

logger = logging.getLogger(__name__)

#: 第 n 次失敗後等待的秒數；第 MAX_ATTEMPTS 次仍失敗就放棄
BACKOFF: tuple[int, ...] = (10, 60, 300, 900, 1800, 3600, 7200)
MAX_ATTEMPTS = len(BACKOFF) + 1
#: 取到期通知的間隔（秒）
POLL_INTERVAL = 2.0
#: 每次最多取幾筆
BATCH = 20
#: 連線與讀取的逾時（秒）
TIMEOUT = 10.0
#: 雖然是 4xx 但值得重試的狀態碼
RETRY_STATUSES = frozenset({408, 429})
#: 記錄回應內容的長度上限
ERROR_CHARS = 500


@dataclass(frozen=True)
class Outcome:
    delivered: bool
    #: 失敗時是否值得重試
    retry: bool
    error: str | None


async def send(http: httpx.AsyncClient, settings: Settings, row: WebhookOutboxRow, now: datetime) -> Outcome:
    body = encode(row.payload)
    timestamp = int(now.timestamp())
    secret = settings.job_webhook_secret.get_secret_value()
    try:
        res = await http.post(
            settings.job_webhook_url,
            content=body,
            headers=headers(webhook_id=row.id, event=row.event, secret=secret, timestamp=timestamp, body=body),
        )
    except httpx.HTTPError as error:
        return Outcome(False, True, f'連線失敗：{error!r}')
    if 200 <= res.status_code < 300:
        return Outcome(True, False, None)
    retry = res.status_code >= 500 or res.status_code in RETRY_STATUSES
    return Outcome(False, retry, f'HTTP {res.status_code}：{res.text[:ERROR_CHARS]}')


def apply_outcome(row: WebhookOutboxRow, outcome: Outcome, now: datetime) -> None:
    row.attempts += 1
    if outcome.delivered:
        row.status, row.delivered_at, row.last_error = 'delivered', now, None
    elif not outcome.retry or row.attempts >= MAX_ATTEMPTS:
        row.status, row.last_error = 'dead', outcome.error
    else:
        row.next_attempt_at = now + timedelta(seconds=BACKOFF[row.attempts - 1])
        row.last_error = outcome.error


async def deliver_due(db: Database, settings: Settings, http: httpx.AsyncClient, now: datetime) -> int:
    if not settings.job_webhook_url:
        return 0
    delivered = 0
    async with db.session() as s:
        rows = (
            await s.scalars(
                select(WebhookOutboxRow)
                .where(WebhookOutboxRow.status == 'pending', WebhookOutboxRow.next_attempt_at <= now)
                .order_by(WebhookOutboxRow.next_attempt_at)
                .limit(BATCH)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for row in rows:
            outcome = await send(http, settings, row, now)
            apply_outcome(row, outcome, now)
            if outcome.delivered:
                delivered += 1
            elif row.status == 'dead':
                logger.warning('webhook 放棄發送：%s（任務 %s）：%s', row.id, row.job_id, row.last_error)
        await s.commit()
    return delivered


async def deliver_periodically(db: Database, settings: Settings, interval: float = POLL_INTERVAL) -> None:
    """worker 執行期間一直發送；出錯只記錄，下一輪再試。"""
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as http:
        while True:
            try:
                await deliver_due(db, settings, http, utc_now())
            except Exception:
                logger.exception('發送 webhook 失敗')
            await asyncio.sleep(interval)
```

- [ ] **Step 4：確認通過**

Run: `uv run pytest tests/test_webhook_delivery.py -v`
Expected: PASS

- [ ] **Step 5：worker 啟動發送迴圈**

`backend/app/worker.py`：匯入 `from app.webhooks.delivery import deliver_periodically`。`main` 內 `cleaning = ...` 之後加入：

```python
    # 任務結束的通知（JOB_WEBHOOK_URL 有設定時）：每 2 秒發送到期的通知，失敗依退避表重試
    delivering = (
        asyncio.create_task(deliver_periodically(services.db, services.settings))
        if services.settings.job_webhook_url
        else None
    )
```

`finally` 內 `cleaning.cancel()` 之後加入：

```python
        if delivering is not None:
            delivering.cancel()
```

模組 docstring 的清單最後加一行：`- 任務結束的通知：JOB_WEBHOOK_URL 有設定時，每 2 秒發送 outbox 裡到期的通知（失敗依退避表重試）`。

- [ ] **Step 6：整套後端測試、型別與格式**

Run: `uv run pytest && uv run mypy app tests && uv run ruff check . && uv run ruff format --check .`
Expected: 全部 PASS

- [ ] **Step 7：Commit**

```bash
git add backend/app/webhooks/delivery.py backend/app/worker.py backend/tests/test_webhook_delivery.py
git commit -m "feat: deliver job webhooks with signed retries from the worker"
```

---

### Task 5：自動化 API 的驗證與建任務

**Files:**
- Modify: `backend/app/api/jobs.py`
- Create: `backend/app/api/automation.py`
- Modify: `backend/app/api/main.py`
- Test: `backend/tests/test_api_automation.py`

**Interfaces:**
- Consumes: `Unauthorized`、`Settings.automation_*`（Task 1）；`repo.jobs.create_job(..., client_ref, parent_job_id, reviewer_feedback)`（Task 3）
- Produces:
  - `api.jobs.JobMeta(client_ref: str | None = None, parent_job_id: str | None = None, reviewer_feedback: str | None = None)`（frozen dataclass）
  - `async def parse_text(services: ApiServices, brand: Brand, text: str, product: Product | None) -> ParsedBrief`
  - `async def submit_job(services: ApiServices, job_input: JobInput, meta: JobMeta = JobMeta()) -> str`（回傳 job_id）
  - `api.automation.router`（prefix `/api/automation`）、`require_token`
  - `POST /api/automation/jobs` → 201 `JobCreated`

- [ ] **Step 1：寫失敗的測試** `backend/tests/test_api_automation.py`

```python
"""自動化 API：token 驗證、伺服器端拆解需求並補齊預設值、client_ref 存進任務。需要 composer。"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.contract import JobInput, ParsedBrief
from app.db.models import JobRow
from tests.conftest import LiveApi
from tests.fixtures import load_fixture

TOKEN = 't' * 32
AUTH = {'Authorization': f'Bearer {TOKEN}'}
#: 與 test_api_jobs 相同的劇本：SimAgent 對這句需求的拆解結果就是劇本的 parsedBrief
FIXTURE = load_fixture('timelines/selune-retry.json')['input']
BRIEF = {'brandId': FIXTURE['brandId'], 'productId': FIXTURE['productId'], 'brief': FIXTURE['brief']}


@pytest.fixture
async def automation(api: LiveApi) -> AsyncIterator[LiveApi]:
    api.services.settings.automation_token = SecretStr(TOKEN)
    yield api
    api.services.settings.automation_token = SecretStr('')


async def job_row(api: LiveApi, job_id: str) -> JobRow:
    async with api.services.db.session() as s:
        row = await s.scalar(select(JobRow).where(JobRow.id == job_id))
        assert row is not None
        return row


async def test_disabled_without_a_token(api: LiveApi) -> None:
    res = await api.http.post('/api/automation/jobs', json=BRIEF, headers=AUTH)
    assert res.status_code == 404


@pytest.mark.parametrize('headers', [{}, {'Authorization': 'Bearer wrong'}, {'Authorization': f'Basic {TOKEN}'}])
async def test_rejects_missing_or_wrong_tokens(automation: LiveApi, headers: dict[str, str]) -> None:
    res = await automation.http.post('/api/automation/jobs', json=BRIEF, headers=headers)
    assert res.status_code == 401
    assert res.json() == {'error': {'code': 'unauthorized', 'message': '缺少或錯誤的 automation token'}}
    assert TOKEN not in res.text


async def test_create_job_fills_in_the_defaults(automation: LiveApi) -> None:
    res = await automation.http.post('/api/automation/jobs', json={**BRIEF, 'clientRef': 'sheet:abc:row:2'}, headers=AUTH)
    assert res.status_code == 201
    row = await job_row(automation, res.json()['jobId'])
    assert (row.stage, row.client_ref, row.parent_job_id, row.reviewer_feedback) == ('queued', 'sheet:abc:row:2', None, None)
    inp = JobInput.model_validate(row.input)
    assert inp.brief == BRIEF['brief']
    assert inp.template_ids == ['ig-post', 'story', 'ecom-main']
    assert (inp.variants_per_template, inp.max_retries, inp.visual_style_id) == (2, 2, None)
    assert inp.parsed_brief == ParsedBrief.model_validate(FIXTURE['parsedBrief'])
    options = (await automation.http.get('/api/options')).json()
    assert (inp.llm, inp.vlm, inp.engine) == (options['llm'][0], options['vlm'][0], options['engines'][0])


async def test_create_job_with_explicit_options(automation: LiveApi) -> None:
    body: dict[str, Any] = {**BRIEF, 'templateIds': ['banner'], 'variantsPerTemplate': 1}
    res = await automation.http.post('/api/automation/jobs', json=body, headers=AUTH)
    inp = JobInput.model_validate((await job_row(automation, res.json()['jobId'])).input)
    assert (inp.template_ids, inp.variants_per_template) == (['banner'], 1)


async def test_create_job_reports_invalid_input(automation: LiveApi) -> None:
    res = await automation.http.post('/api/automation/jobs', json={**BRIEF, 'productId': 'nope'}, headers=AUTH)
    assert res.json() == {'error': {'code': 'invalid', 'message': '找不到商品：nope'}}
    res = await automation.http.post('/api/automation/jobs', json={**BRIEF, 'brief': ''}, headers=AUTH)
    assert res.status_code == 400
```


- [ ] **Step 2：確認失敗**

Run: `uv run pytest tests/test_api_automation.py -v`
Expected: FAIL（404：路由不存在，含應為 401 與 201 的測試）

- [ ] **Step 3：從 `api/jobs.py` 抽出共用函式**

在 `backend/app/api/jobs.py`：匯入加上 `from dataclasses import dataclass`、`from app.contract import Brand, Product`。

把 `parse_brief` 的 Gemini 呼叫抽成：

```python
async def parse_text(services: ApiServices, brand: Brand, text: str, product: Product | None) -> ParsedBrief:
    try:
        return await asyncio.wait_for(services.agent.parse_brief(brand, text, product), BRIEF_TIMEOUT)
    except TimeoutError as error:
        raise Unavailable(f'Gemini 沒有在 {BRIEF_TIMEOUT} 秒內完成需求拆解，請稍後再試') from error
```

`parse_brief` 最後改為 `return await parse_text(services, brand, body.text, product)`。

新增：

```python
@dataclass(frozen=True)
class JobMeta:
    """自動化建立的任務另外記錄的欄位（不在 JobInput 合約裡）。"""

    client_ref: str | None = None
    parent_job_id: str | None = None
    reviewer_feedback: str | None = None
```

把 `create_job` 路由的內容搬到：

```python
async def submit_job(services: ApiServices, job_input: JobInput, meta: JobMeta = JobMeta()) -> str:
    """檢查、寫入任務、送出 job.accepted 與 job.status queued，放進 jobs 佇列；回傳任務 id。"""
    await _validate(services, job_input)
    now = utc_now()
    local = now.astimezone(ZoneInfo(services.settings.timezone))
    for attempt in range(5):
        job_id = jobs.make_job_id(local)
        try:
            async with services.db.session() as s:
                await jobs.create_job(
                    s, job_id, job_input, now,
                    client_ref=meta.client_ref, parent_job_id=meta.parent_job_id,
                    reviewer_feedback=meta.reviewer_feedback,
                )
            break
        except IntegrityError:
            # 同一分鐘內 4 位亂數重複：換一個
            if attempt == 4:
                raise
    await services.store.append(job_id, JobAcceptedEvent(type='job.accepted', job_id=job_id))
    await services.store.append(job_id, JobStatusEvent(type='job.status', stage='queued', round=0))
    try:
        await services.queues.enqueue_job(job_id)
    except Exception as error:  # noqa: BLE001 - 佇列的任何錯誤都要讓任務結束，不能留在排隊中
        logger.exception('任務無法排入佇列：job_id=%s', job_id)
        if not await _fail_unless_taken(services, job_id):
            raise Unavailable('目前無法排入任務（佇列服務沒有回應），請稍後再試') from error
    return job_id
```

路由改為：

```python
@router.post('/api/jobs', status_code=201)
async def create_job(job_input: JobInput, services: Services) -> JobCreated:
    """寫入任務、送出 job.accepted 與 job.status queued，放進 jobs 佇列。"""
    return JobCreated(job_id=await submit_job(services, job_input))
```

- [ ] **Step 4：確認既有任務 API 的測試仍通過**

Run: `uv run pytest tests/test_api_jobs.py -v`
Expected: PASS

- [ ] **Step 5：實作** `backend/app/api/automation.py`

```python
"""n8n 等自動化呼叫端的 API（Authorization: Bearer AUTOMATION_TOKEN）。

內部重用 Studio 的建任務與選圖邏輯；AUTOMATION_TOKEN 為空時整組回 404（像是不存在）。
"""

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import Field

from app.api.catalog import api_options
from app.api.jobs import JobCreated, JobMeta, parse_text, submit_job
from app.api.services import Services
from app.contract import JobInput, Model, TemplateId
from app.errors import Invalid, NotFound, Unauthorized
from app.repo import catalog

#: 與 Studio 的預設相同（web/src/lib/store/studio.ts）
DEFAULT_MAX_RETRIES = 2


async def require_token(services: Services, authorization: Annotated[str | None, Header()] = None) -> None:
    token = services.settings.automation_token.get_secret_value()
    if not token:
        raise NotFound('找不到這個網址')
    scheme, _, given = (authorization or '').partition(' ')
    if scheme.lower() != 'bearer' or not hmac.compare_digest(given.encode(), token.encode()):
        raise Unauthorized('缺少或錯誤的 automation token')


router = APIRouter(prefix='/api/automation', tags=['自動化'], dependencies=[Depends(require_token)])


class AutomationJobRequest(Model):
    brand_id: str
    product_id: str
    brief: str = Field(min_length=1, max_length=500)
    #: 呼叫端的參照（例如 sheet:<id>:row:12）：原樣存起來，在 webhook 帶回
    client_ref: str | None = Field(default=None, max_length=200)
    template_ids: list[TemplateId] | None = None
    variants_per_template: int | None = None
    visual_style_id: str | None = None


@router.post('/jobs', status_code=201)
async def create_job(body: AutomationJobRequest, services: Services) -> JobCreated:
    """在伺服器端拆解需求，其餘欄位以設定與可用選項的預設值補齊，再走與 Studio 相同的建任務流程。"""
    async with services.db.session() as s:
        brand = await catalog.get_brand(s, body.brand_id)
        product = await catalog.get_product(s, body.product_id)
    if brand is None:
        raise Invalid(f'找不到品牌：{body.brand_id}')
    if product is None:
        raise Invalid(f'找不到商品：{body.product_id}')
    parsed = await parse_text(services, brand, body.brief, product)
    settings = services.settings
    options = api_options(settings)
    job_input = JobInput(
        brand_id=body.brand_id,
        product_id=body.product_id,
        brief=body.brief,
        parsed_brief=parsed,
        template_ids=body.template_ids or list(settings.automation_templates),
        variants_per_template=body.variants_per_template or settings.automation_variants,
        llm=options.llm[0],
        engine=options.engines[0],
        vlm=options.vlm[0],
        max_retries=DEFAULT_MAX_RETRIES,
        visual_style_id=body.visual_style_id,
    )
    return JobCreated(job_id=await submit_job(services, job_input, JobMeta(client_ref=body.client_ref)))
```

`backend/app/api/main.py`：`from app.api import automation, catalog, files, jobs`，並在 `app.include_router(jobs.router)` 之後加 `app.include_router(automation.router)`。

- [ ] **Step 6：確認通過**

Run: `uv run pytest tests/test_api_automation.py tests/test_api_jobs.py -v`
Expected: PASS

- [ ] **Step 7：型別與格式**

Run: `uv run mypy app tests && uv run ruff check . && uv run ruff format --check .`
Expected: 沒有錯誤

- [ ] **Step 8：Commit**

```bash
git add backend/app/api/jobs.py backend/app/api/automation.py backend/app/api/main.py backend/tests/test_api_automation.py
git commit -m "feat: add the token-protected automation job endpoint"
```

---

### Task 6：核准、退回與冪等

**Files:**
- Modify: `backend/app/api/jobs.py`（抽出 `record_selection`）
- Modify: `backend/app/repo/jobs.py`（`ancestor_count`）
- Modify: `backend/app/api/automation.py`
- Test: `backend/tests/test_api_automation.py`

**Interfaces:**
- Consumes: `submit_job`、`JobMeta`（Task 5）；`payload.candidates`、`payload.best`（Task 2）；`AutomationRequestRow`（Task 1）
- Produces:
  - `async def record_selection(services: ApiServices, job_id: str, render_id: str, copy: Copy) -> HistoryEntry`
  - `async def ancestor_count(session: AsyncSession, job_id: str, limit: int) -> int`
  - `POST /api/automation/jobs/{job_id}/approve`（body `{renderId?}`）→ 201 `HistoryEntry`
  - `POST /api/automation/jobs/{job_id}/revise`（body `{feedback}`）→ 201 `JobCreated`
  - `MAX_REVISIONS = 3`、`IDEMPOTENCY_DAYS = 7`

- [ ] **Step 1：寫失敗的測試**（加在 `backend/tests/test_api_automation.py`）

檔頭匯入加上 `from tests.test_api_jobs import stream`、`from app.db.models import AutomationRequestRow, HistoryRow`、`from datetime import timedelta`、`from app.core.clock import utc_now`。

```python
@pytest.fixture
async def running(automation: LiveApi) -> AsyncIterator[LiveApi]:
    """整個測試期間 worker 都在執行：任務跑得完，選定後的歷史回寫也不必等到逾時。"""
    async with automation.worker(speed=0):
        yield automation


async def finished_job(api: LiveApi, **extra: Any) -> str:
    """以自動化 API 建立任務並等它跑完（模擬模式、不等待時間軸；需要 running fixture）。"""
    res = await api.http.post('/api/automation/jobs', json={**BRIEF, 'templateIds': ['story'], **extra}, headers=AUTH)
    job_id: str = res.json()['jobId']
    await stream(api, job_id)
    return job_id


async def test_approve_defaults_to_the_best_render(running: LiveApi) -> None:
    automation = running
    job_id = await finished_job(automation)
    res = await automation.http.post(f'/api/automation/jobs/{job_id}/approve', json={}, headers=AUTH)
    assert res.status_code == 201
    entry = res.json()
    snap = (await automation.http.get(f'/api/jobs/{job_id}')).json()
    assert entry['render']['id'] == snap['summary']['bestRenderIds']['story']
    assert entry['copy'] == entry['render']['spec']['copy']


async def test_approve_a_specific_render_and_reject_unknown_ones(running: LiveApi) -> None:
    automation = running
    job_id = await finished_job(automation)
    snap = (await automation.http.get(f'/api/jobs/{job_id}')).json()
    first = next(e for e in snap['events'] if e['type'] == 'render.completed')['renders'][0]['id']
    res = await automation.http.post(f'/api/automation/jobs/{job_id}/approve', json={'renderId': first}, headers=AUTH)
    assert res.json()['render']['id'] == first
    res = await automation.http.post(f'/api/automation/jobs/{job_id}/approve', json={'renderId': 'nope'}, headers=AUTH)
    assert res.json() == {'error': {'code': 'not_found', 'message': '找不到候選圖：nope'}}


async def test_approve_needs_a_finished_job_with_renders(automation: LiveApi) -> None:
    res = await automation.http.post('/api/automation/jobs', json=BRIEF, headers=AUTH)  # 沒有 worker：停在排隊中
    job_id = res.json()['jobId']
    res = await automation.http.post(f'/api/automation/jobs/{job_id}/approve', json={}, headers=AUTH)
    assert res.json() == {'error': {'code': 'conflict', 'message': '任務還沒有可選的候選圖（目前階段：queued）'}}


async def test_revise_creates_a_child_job(running: LiveApi) -> None:
    automation = running
    job_id = await finished_job(automation, clientRef='sheet:abc:row:5')
    res = await automation.http.post(f'/api/automation/jobs/{job_id}/revise', json={'feedback': '標題改成限時三天'}, headers=AUTH)
    assert res.status_code == 201
    child = await job_row(automation, res.json()['jobId'])
    parent = await job_row(automation, job_id)
    assert (child.parent_job_id, child.reviewer_feedback, child.client_ref) == (job_id, '標題改成限時三天', 'sheet:abc:row:5')
    assert child.input == parent.input


async def test_revise_needs_a_finished_job(automation: LiveApi) -> None:
    job_id = (await automation.http.post('/api/automation/jobs', json=BRIEF, headers=AUTH)).json()['jobId']
    res = await automation.http.post(f'/api/automation/jobs/{job_id}/revise', json={'feedback': 'x'}, headers=AUTH)
    assert res.json() == {'error': {'code': 'conflict', 'message': '任務還沒結束，不能退回'}}


async def test_revise_stops_after_three_revisions(running: LiveApi) -> None:
    automation = running
    job_id = await finished_job(automation)
    for n in range(3):
        res = await automation.http.post(f'/api/automation/jobs/{job_id}/revise', json={'feedback': f'第 {n + 1} 次'}, headers=AUTH)
        assert res.status_code == 201
        job_id = res.json()['jobId']
        await stream(automation, job_id)
    res = await automation.http.post(f'/api/automation/jobs/{job_id}/revise', json={'feedback': '第 4 次'}, headers=AUTH)
    assert res.json() == {'error': {'code': 'conflict', 'message': '已退回 3 次，請到 Studio 手動處理'}}


async def test_idempotency_key_replays_the_first_response(running: LiveApi) -> None:
    automation = running
    job_id = await finished_job(automation)
    headers = {**AUTH, 'Idempotency-Key': 'wh_abc:revise'}
    first = await automation.http.post(f'/api/automation/jobs/{job_id}/revise', json={'feedback': 'a'}, headers=headers)
    again = await automation.http.post(f'/api/automation/jobs/{job_id}/revise', json={'feedback': 'a'}, headers=headers)
    assert (first.status_code, again.status_code) == (201, 201)
    assert first.json() == again.json()
    async with automation.services.db.session() as s:
        children = list(await s.scalars(select(JobRow).where(JobRow.parent_job_id == job_id)))
    assert len(children) == 1
    headers = {**AUTH, 'Idempotency-Key': 'wh_abc:approve'}
    for _ in range(2):
        await automation.http.post(f'/api/automation/jobs/{job_id}/approve', json={}, headers=headers)
    async with automation.services.db.session() as s:
        assert len(list(await s.scalars(select(HistoryRow).where(HistoryRow.job_id == job_id)))) == 1


async def test_failed_requests_release_the_idempotency_key(automation: LiveApi) -> None:
    headers = {**AUTH, 'Idempotency-Key': 'k1'}
    res = await automation.http.post('/api/automation/jobs/job_nope/approve', json={}, headers=headers)
    assert res.status_code == 404
    async with automation.services.db.session() as s:
        assert await s.get(AutomationRequestRow, ('k1', 'approve')) is None


async def test_old_idempotency_keys_are_removed(running: LiveApi) -> None:
    automation = running
    async with automation.services.db.session() as s:
        s.add(AutomationRequestRow(key='old', action='approve', job_id='j', response={}, created_at=utc_now() - timedelta(days=8)))
        await s.commit()
    job_id = await finished_job(automation)
    await automation.http.post(f'/api/automation/jobs/{job_id}/approve', json={}, headers={**AUTH, 'Idempotency-Key': 'new'})
    async with automation.services.db.session() as s:
        assert await s.get(AutomationRequestRow, ('old', 'approve')) is None
        assert await s.get(AutomationRequestRow, ('new', 'approve')) is not None
```

- [ ] **Step 2：確認失敗**

Run: `uv run pytest tests/test_api_automation.py -v`
Expected: 新測試 FAIL（405 或 404：路由不存在）

- [ ] **Step 3：抽出 `record_selection`**

`backend/app/api/jobs.py`：把 `select_render` 的內容搬到

```python
async def record_selection(services: ApiServices, job_id: str, render_id: str, copy: Copy) -> HistoryEntry:
    """選定候選圖：寫入歷史紀錄，再由 worker 回寫成歷史切塊（writtenToRag）。

    回寫最多等 WRITE_BACK_WAIT 秒；逾時、失敗或被中止時 writtenToRag 為 false。歷史紀錄已經建立，所以不回錯誤。
    """
```

函式內把 `body.render_id` 換成 `render_id`、`body.copy_` 換成 `copy`，其餘不變。路由改為：

```python
@router.post('/api/jobs/{job_id}/select', status_code=201)
async def select_render(job_id: str, body: SelectRequest, services: Services) -> HistoryEntry:
    return await record_selection(services, job_id, body.render_id, body.copy_)
```

Run: `uv run pytest tests/test_api_jobs.py -v`
Expected: PASS

- [ ] **Step 4：`ancestor_count`**

`backend/app/repo/jobs.py` 最後加入：

```python
async def ancestor_count(session: AsyncSession, job_id: str, limit: int) -> int:
    """沿著 parent_job_id 往上數有幾個上層任務（最多數到 limit）。"""
    count = 0
    current = await session.scalar(select(JobRow.parent_job_id).where(JobRow.id == job_id))
    while current is not None and count < limit:
        count += 1
        current = await session.scalar(select(JobRow.parent_job_id).where(JobRow.id == current))
    return count
```

- [ ] **Step 5：核准、退回與冪等**

`backend/app/api/automation.py` 匯入加上：

```python
from collections.abc import Awaitable, Callable
from datetime import timedelta

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.jobs import record_selection
from app.contract import FINISHED_STAGES, HistoryEntry
from app.core.clock import utc_now
from app.db.models import AutomationRequestRow, JobRow
from app.errors import Conflict
from app.repo import jobs
from app.webhooks.payload import best, candidates
```

加入：

```python
#: 一條退回鏈最多幾次
MAX_REVISIONS = 3
#: 冪等鍵保留的天數
IDEMPOTENCY_DAYS = 7

IdempotencyKey = Annotated[str | None, Header(alias='Idempotency-Key', max_length=100)]


async def idempotent[M: Model](
    services: Services, key: str | None, action: str, job_id: str, model: type[M], run: Callable[[], Awaitable[M]]
) -> M:
    """同一個 (key, action) 只執行一次：先佔用鍵，執行成功後存下回應；再次呼叫時回傳存下的回應。
    執行失敗時放掉鍵（呼叫端可以重試）；另一個相同的請求還在處理中時回 409。"""
    if key is None:
        return await run()
    now = utc_now()
    async with services.db.session() as s:
        await s.execute(delete(AutomationRequestRow).where(AutomationRequestRow.created_at < now - timedelta(days=IDEMPOTENCY_DAYS)))
        claimed = await s.execute(
            pg_insert(AutomationRequestRow)
            .values(key=key, action=action, job_id=job_id, response=None, created_at=now)
            .on_conflict_do_nothing()
            .returning(AutomationRequestRow.key)
        )
        mine = claimed.scalar() is not None
        await s.commit()
        if not mine:
            row = await s.get(AutomationRequestRow, (key, action))
            if row is None or row.response is None:
                raise Conflict('同一個請求正在處理中，請稍後再試')
            return model.model_validate(row.response)
    try:
        result = await run()
    except BaseException:
        async with services.db.session() as s:
            await s.execute(delete(AutomationRequestRow).where(AutomationRequestRow.key == key, AutomationRequestRow.action == action))
            await s.commit()
        raise
    async with services.db.session() as s:
        row = await s.get(AutomationRequestRow, (key, action))
        assert row is not None
        row.response = result.to_json()
        await s.commit()
    return result


class ApproveRequest(Model):
    #: 不填就用分數最高的候選圖
    render_id: str | None = None


class ReviseRequest(Model):
    feedback: str = Field(min_length=1, max_length=500)


@router.post('/jobs/{job_id}/approve', status_code=201)
async def approve(job_id: str, body: ApproveRequest, services: Services, idempotency_key: IdempotencyKey = None) -> HistoryEntry:
    """以候選圖本身的文案選定它（寫入歷史紀錄並回寫 RAG），與 Studio 的選定相同。"""

    async def run() -> HistoryEntry:
        async with services.db.session() as s:
            snap = await jobs.get_job(s, job_id)
            if snap is None:
                raise NotFound(f'找不到任務：{job_id}')
            if snap.summary.stage not in ('done', 'needs_review'):
                raise Conflict(f'任務還沒有可選的候選圖（目前階段：{snap.summary.stage}）')
            render_id = body.render_id
            if render_id is None:
                top = best(candidates(snap.summary.best_render_ids, snap.events))
                if top is None:
                    raise Conflict('任務沒有審查過的候選圖')
                render_id = top['renderId']
            render = await jobs.get_render(s, job_id, render_id)
        if render is None:
            raise NotFound(f'找不到候選圖：{render_id}')
        return await record_selection(services, job_id, render_id, render.spec.copy_)

    return await idempotent(services, idempotency_key, 'approve', job_id, HistoryEntry, run)


@router.post('/jobs/{job_id}/revise', status_code=201)
async def revise(job_id: str, body: ReviseRequest, services: Services, idempotency_key: IdempotencyKey = None) -> JobCreated:
    """以原任務的輸入另開新任務，附上審核者的修改意見；client_ref 沿用，parent_job_id 指向原任務。"""

    async def run() -> JobCreated:
        async with services.db.session() as s:
            row = await s.get(JobRow, job_id)
            if row is None:
                raise NotFound(f'找不到任務：{job_id}')
            if row.stage not in FINISHED_STAGES:
                raise Conflict('任務還沒結束，不能退回')
            if await jobs.ancestor_count(s, job_id, MAX_REVISIONS) >= MAX_REVISIONS:
                raise Conflict(f'已退回 {MAX_REVISIONS} 次，請到 Studio 手動處理')
            job_input = JobInput.model_validate(row.input)
            meta = JobMeta(client_ref=row.client_ref, parent_job_id=job_id, reviewer_feedback=body.feedback)
        return JobCreated(job_id=await submit_job(services, job_input, meta))

    return await idempotent(services, idempotency_key, 'revise', job_id, JobCreated, run)
```

> `snap.events` 是含 `seq`、`ts` 的訊息，`candidates` 只讀 `type`、`renders`、`renderId`、`check`、`score`、`passed`、`image`，可以直接傳入。

- [ ] **Step 6：確認通過**

Run: `uv run pytest tests/test_api_automation.py tests/test_api_jobs.py -v`
Expected: PASS

- [ ] **Step 7：型別與格式**

Run: `uv run mypy app tests && uv run ruff check . && uv run ruff format --check .`
Expected: 沒有錯誤

- [ ] **Step 8：Commit**

```bash
git add backend/app/api/jobs.py backend/app/api/automation.py backend/app/repo/jobs.py backend/tests/test_api_automation.py
git commit -m "feat: approve and revise jobs through the automation API with idempotency keys"
```

---

### Task 7：退回意見進入流程

**Files:**
- Modify: `backend/app/pipeline/runner.py`
- Modify: `backend/app/pipeline/ports.py`
- Modify: `backend/app/pipeline/gemini.py`
- Modify: `backend/app/pipeline/prompts/spec.md`
- Modify: `backend/app/adapters/composer.py`
- Test: `backend/tests/test_pipeline.py`、`backend/tests/test_gemini_agent.py`

**Interfaces:**
- Consumes: `JobRow.reviewer_feedback`、`JobRow.parent_job_id`（Task 1）
- Produces:
  - `JobContext.feedback: str | None = None`、`JobContext.parent_job_id: str | None = None`
  - `SpecRequest.feedback: str | None = None`
  - `runner.with_feedback(job_input: JobInput, feedback: str | None) -> JobInput`
  - `composer.guard_text(r: SpecRequest) -> str`
  - Gemini spec payload 的 `reviewerFeedback` 欄位

- [ ] **Step 1：寫失敗的測試**

`backend/tests/test_pipeline.py`：匯入加上 `from app.db.models import JobRow`。在檔案最後加入：

```python
class RecordingRetriever(EmptyRetriever):
    """記錄收到的需求文字（RAG 查詢的一部分）。"""

    def __init__(self) -> None:
        super().__init__()
        self.briefs: list[str] = []

    async def retrieve(
        self, brand: Brand, product: Product, job_input: JobInput, run: RunContext
    ) -> tuple[str, list[RagHit]]:
        self.briefs.append(job_input.brief)
        return await super().retrieve(brand, product, job_input, run)


FIXTURE_BRIEF = load_fixture('timelines/selune-retry.json')['input']['brief']


async def set_feedback(db: Database, feedback: str) -> None:
    """把 store fixture 建立的任務改成「由 job_parent 退回」的任務。"""
    async with db.session() as s:
        parent_input = JobInput.model_validate(load_fixture('timelines/selune-retry.json')['input'])
        await jobs.create_job(s, 'job_parent', parent_input, NOW)
        row = await s.get(JobRow, JOB)
        assert row is not None
        row.reviewer_feedback, row.parent_job_id = feedback, 'job_parent'
        await s.commit()


async def all_events(db: Database) -> list[dict[str, Any]]:
    async with db.session() as s:
        snap = await jobs.get_job(s, JOB)
    assert snap is not None
    return snap.events


async def test_reviewer_feedback_reaches_the_log_rag_and_prompt(store: EventStore, db: Database) -> None:
    await set_feedback(db, '標題改成限時三天')
    agent, retriever = FakeAgent(), RecordingRetriever()
    reviewer = FakeReviewer({1: {'ig-post', 'story'}})
    await run_job(JOB, db, store, ports(agent, reviewer, retriever=retriever), speed=0)
    assert retriever.briefs == [f'{FIXTURE_BRIEF}｜審核者的修改意見：標題改成限時三天']
    assert agent.requests and {r.feedback for r in agent.requests} == {'標題改成限時三天'}
    assert {r.text for r in agent.requests} == {FIXTURE_BRIEF}  # 一句話需求本身不變
    events = await all_events(db)
    warn = next(i for i, m in enumerate(events) if m['type'] == 'log' and m['message'].startswith('審核者退回'))
    assert events[warn] == {
        **events[warn], 'source': 'agent', 'level': 'warn', 'message': '審核者退回（job_parent）：標題改成限時三天'
    }
    assert warn < next(i for i, m in enumerate(events) if m['type'] == 'brief.parsed')


async def test_jobs_without_feedback_are_unchanged(store: EventStore, db: Database) -> None:
    agent, retriever = FakeAgent(), RecordingRetriever()
    await run_job(JOB, db, store, ports(agent, FakeReviewer({1: {'ig-post', 'story'}}), retriever=retriever), speed=0)
    assert retriever.briefs == [FIXTURE_BRIEF]
    assert {r.feedback for r in agent.requests} == {None}
    assert not any(m['type'] == 'log' and m['message'].startswith('審核者退回') for m in await all_events(db))
```

`backend/tests/test_gemini_agent.py`：匯入改為 `from app.adapters.composer import ComposerClient, brand_json, guard_text, spec_request_json`。在「Prompt 構建」相關測試之後加入：

```python
async def test_reviewer_feedback_goes_to_gemini(composer: ComposerClient) -> None:
    gemini = FakeGemini(spec=[GOOD, GOOD])
    agent = GeminiAgent(gemini, composer, SETTINGS)
    await agent.build_spec(await request(composer), FakeRun('job_agent'))
    await agent.build_spec(await request(composer, feedback='標題改成限時三天'), FakeRun('job_agent'))
    first, second = gemini.calls
    assert json.loads(user_text(first))['reviewerFeedback'] is None
    assert json.loads(user_text(second))['reviewerFeedback'] == '標題改成限時三天'


async def test_the_offer_guard_treats_the_feedback_as_part_of_the_brief(composer: ComposerClient) -> None:
    """護欄判斷「需求沒提到的價格與優惠」時，意見裡寫的價格可以出現在文案。"""
    plain = await request(composer)
    assert guard_text(plain) == TEXT
    assert spec_request_json(plain)['text'] == TEXT
    revised = await request(composer, feedback='改成 399 元')
    assert guard_text(revised) == f'{TEXT} 改成 399 元'
    assert spec_request_json(revised)['text'] == f'{TEXT} 改成 399 元'
```

- [ ] **Step 2：確認失敗**

Run: `uv run pytest tests/test_pipeline.py tests/test_gemini_agent.py -v`
Expected: 新測試 FAIL（`SpecRequest` 沒有 `feedback`、`guard_text` 不存在、沒有 log）

- [ ] **Step 3：`SpecRequest.feedback`**

`backend/app/pipeline/ports.py` 的 `SpecRequest` 最後（`previous` 之後）加入：

```python
    #: 審核者的修改意見（由「退回並重新生成」建立的任務）；沒有時為 None
    feedback: str | None = None
```

- [ ] **Step 4：runner**

`backend/app/pipeline/runner.py`：

`JobContext` 加入兩個欄位（放在最後，給預設值）：

```python
    #: 審核者的修改意見與被退回的任務（由「退回並重新生成」建立時）
    feedback: str | None = None
    parent_job_id: str | None = None
```

`_load` 的回傳改為：

```python
    return JobContext(
        job_id, job_input, brand, product, templates, feedback=row.reviewer_feedback, parent_job_id=row.parent_job_id
    )
```

（`row` 在 `async with` 區塊外仍可讀已載入的屬性；若 mypy 或 SQLAlchemy 抱怨 detached，先在區塊內把兩個值存到區域變數。）

新增：

```python
def with_feedback(job_input: JobInput, feedback: str | None) -> JobInput:
    """RAG 查詢用的輸入：把審核者的意見接在需求後面，讓相關規範也一起被召回。"""
    if not feedback:
        return job_input
    return job_input.model_copy(update={'brief': f'{job_input.brief}｜審核者的修改意見：{feedback}'})
```

`_pipeline` 在第一則 `run.log('ws', '→ job.create ...')` 之後加入：

```python
    if ctx.feedback:
        await run.log('agent', f'審核者退回（{ctx.parent_job_id}）：{ctx.feedback}', 'warn')
```

RAG 那一行改為：

```python
    query, hits = await ports.retriever.retrieve(brand, product, with_feedback(inp, ctx.feedback), run)
```

建立 `SpecRequest(...)` 的參數最後加 `feedback=ctx.feedback,`。

- [ ] **Step 5：Gemini payload 與提示詞**

`backend/app/pipeline/gemini.py` 的 `_spec_payload`：在 `'brief': {...},` 之後加入 `'reviewerFeedback': request.feedback,`。

`backend/app/pipeline/prompts/spec.md`：「## 輸入」清單在 `brief` 之後加：

```markdown
- `reviewerFeedback`：審核者退回時寫的修改意見；沒有時為 null。
```

「## 文案」清單最後加：

```markdown
- `reviewerFeedback` 有值時優先照做（例如改標題、改語氣、強調某個賣點），但仍要遵守品牌規範、禁用詞與長度限制。意見裡提到的價格與優惠視同需求提到的。
```

- [ ] **Step 6：護欄的需求文字**

`backend/app/adapters/composer.py`：在 `spec_request_json` 之前加入

```python
def guard_text(r: SpecRequest) -> str:
    """護欄判斷「需求沒提到的價格與優惠」時使用的需求文字：一句話需求加上審核者的意見。"""
    return ' '.join(part for part in (r.text, r.feedback) if part)
```

並把 `spec_request_json` 的 `'text': r.text,` 改為 `'text': guard_text(r),`。

- [ ] **Step 7：確認通過**

Run: `uv run pytest tests/test_pipeline.py tests/test_gemini_agent.py tests/test_parity.py -v`
Expected: PASS（`test_parity` 確認沒有意見時與前端的結果仍一致）

- [ ] **Step 8：整套測試、型別與格式**

Run: `uv run pytest && uv run mypy app tests && uv run ruff check . && uv run ruff format --check .`
Expected: 全部 PASS

- [ ] **Step 9：Commit**

```bash
git add backend/app/pipeline backend/app/adapters/composer.py backend/tests/test_pipeline.py backend/tests/test_gemini_agent.py
git commit -m "feat: feed reviewer feedback into retrieval, prompt building and the offer guard"
```

---

### Task 8：系統狀態的 Webhook 元件

**Files:**
- Modify: `backend/app/api/catalog.py`
- Test: `backend/tests/test_api_catalog.py`

**Interfaces:**
- Consumes: `WebhookOutboxRow`（Task 1）
- Produces: `/api/status` 的元件 `{'id': 'webhook', 'label': 'Webhook（任務結束通知）', ...}`，排在 `cutout` 之後

- [ ] **Step 1：寫失敗的測試**（加在 `backend/tests/test_api_catalog.py`，沿用該檔取得 `/api/status` 的方式）

```python
async def webhook_status(api: LiveApi) -> dict[str, Any]:
    components = (await api.http.get('/api/status')).json()['components']
    return next(c for c in components if c['id'] == 'webhook')


async def test_webhook_status_off_ok_and_error(api: LiveApi) -> None:
    assert await webhook_status(api) == {
        'id': 'webhook', 'label': 'Webhook（任務結束通知）', 'status': 'off', 'detail': '沒有設定 JOB_WEBHOOK_URL',
    }
    api.services.settings.job_webhook_url = 'http://n8n:5678/webhook/x'
    try:
        now = utc_now()
        async with api.services.db.session() as s:
            await jobs.create_job(s, 'job_s', job_input(), now)
            s.add_all([
                WebhookOutboxRow(id='wh_p', job_id='job_s', event='a', payload={}, status='pending', attempts=0, next_attempt_at=now, created_at=now),
                WebhookOutboxRow(id='wh_d', job_id='job_s', event='b', payload={}, status='delivered', attempts=1, next_attempt_at=now, created_at=now),
            ])
            await s.commit()
        assert await webhook_status(api) == {
            'id': 'webhook', 'label': 'Webhook（任務結束通知）', 'status': 'ok', 'detail': '待發送 1 則・已送出 1 則',
        }
        async with api.services.db.session() as s:
            s.add(WebhookOutboxRow(id='wh_x', job_id='job_s', event='c', payload={}, status='dead', attempts=1,
                                   next_attempt_at=now, created_at=now, last_error='HTTP 401：bad signature'))
            await s.commit()
        status = await webhook_status(api)
        assert status['status'] == 'error'
        assert status['detail'] == '1 則通知發送失敗（最後一次：HTTP 401：bad signature）・待發送 1 則'
    finally:
        api.services.settings.job_webhook_url = ''
```

（匯入：`from app.core.clock import utc_now`、`from app.db.models import WebhookOutboxRow`、`from app.repo import jobs`、`from tests.test_jobs import job_input`。）同檔若有斷言 `/api/status` 元件 id 完整清單的測試，把 `'webhook'` 加在最後。

- [ ] **Step 2：確認失敗**

Run: `uv run pytest tests/test_api_catalog.py -v -k "webhook or status"`
Expected: FAIL（`StopIteration`：沒有 webhook 元件）

- [ ] **Step 3：實作**

`backend/app/api/catalog.py`：匯入 `from sqlalchemy import func, select`（已有的 import 合併）、`from app.db.models import WebhookOutboxRow`。新增：

```python
async def _webhook(services: ApiServices) -> str | tuple[ComponentState, str]:
    """有放棄發送（dead）的通知時為 error，附上最後一次的錯誤；其餘顯示待發送與已送出的筆數。"""
    if not services.settings.job_webhook_url:
        return 'off', '沒有設定 JOB_WEBHOOK_URL'
    async with services.db.session() as s:
        rows = await s.execute(select(WebhookOutboxRow.status, func.count()).group_by(WebhookOutboxRow.status))
        counts: dict[str, int] = {status: n for status, n in rows.tuples()}
        pending, delivered, dead = (counts.get(k, 0) for k in ('pending', 'delivered', 'dead'))
        if dead:
            last = await s.scalar(
                select(WebhookOutboxRow.last_error)
                .where(WebhookOutboxRow.status == 'dead')
                .order_by(WebhookOutboxRow.created_at.desc(), WebhookOutboxRow.id.desc())
                .limit(1)
            )
            return 'error', f'{dead} 則通知發送失敗（最後一次：{last}）・待發送 {pending} 則'
    return f'待發送 {pending} 則・已送出 {delivered} 則'
```

`get_status` 改為：

```python
    *probed, gemini, comfyui, cutout, webhook = await asyncio.gather(
        _probe('db', 'PostgreSQL', _db(services)),
        _probe('redis', 'Redis（佇列與事件推送）', _redis(services)),
        _probe('worker', 'worker（SAQ）', _workers(services)),
        _probe('composer', 'composer（排版、繪製與規則審查）', _composer(services)),
        _probe('brands', '品牌設定檔', _brands(services)),
        _probe('chroma', '向量庫（Chroma）', _chroma(services)),
        _probe('rag', 'RAG 模型（BGE-M3＋Reranker）', _rag_model(services)),
        _probe('gemini', 'Gemini（LLM／VLM）', _gemini(services)),
        _probe('comfyui', 'ComfyUI（生圖）', _comfyui(services)),
        _probe('cutout', '去背模型（BiRefNet）', _cutout_model(services)),
        _probe('webhook', 'Webhook（任務結束通知）', _webhook(services)),
    )
    return SystemStatus(components=[*probed, gemini, comfyui, cutout, webhook])
```

- [ ] **Step 4：確認通過；前端的系統狀態元件能顯示新的 id**

Run: `uv run pytest tests/test_api_catalog.py -v`
Expected: PASS

Run（在 `web/`）：`grep -rn "'cutout'" src/components src/lib | head`
Expected: 若前端依 id 白名單顯示元件，把 `'webhook'` 加進白名單與對應的 mock 資料，並執行 `npm test` 與 `npm run typecheck` 確認通過；若是逐筆顯示，不需修改。

- [ ] **Step 5：Commit**

```bash
git add backend/app/api/catalog.py backend/tests/test_api_catalog.py
git commit -m "feat: show webhook delivery health in the system status"
```

（Step 4 有改前端時，一併 `git add` 那些檔案。）

---

### Task 9：compose 與 n8n 工作流

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Create: `n8n/workflows/poster-batch-submit.json`
- Create: `n8n/workflows/poster-job-finished.json`
- Create: `n8n/workflows/poster-error.json`
- Create: `n8n/README.md`
- Test: `backend/tests/test_n8n_workflows.py`

**Interfaces:**
- Consumes: `POST /api/automation/jobs`、`/approve`、`/revise`（Task 5–6）；webhook 標頭與 payload（Task 2）
- Produces: n8n 的 webhook 路徑 `poster-job-finished`；工作流 id `poster-batch-submit`、`poster-job-finished`、`poster-error`

- [ ] **Step 1：寫工作流結構的失敗測試** `backend/tests/test_n8n_workflows.py`

```python
"""n8n 工作流（n8n/workflows/*.json）：必要的節點、webhook 路徑、驗簽程式碼與不含憑證。"""

import json
from pathlib import Path
from typing import Any

import pytest

from app.settings import REPO_ROOT

WORKFLOWS = REPO_ROOT / 'n8n' / 'workflows'


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((WORKFLOWS / f'{name}.json').read_text(encoding='utf-8'))
    return data


def node_types(flow: dict[str, Any]) -> set[str]:
    return {n['type'] for n in flow['nodes']}


def test_the_three_workflows_exist_with_fixed_ids() -> None:
    assert sorted(p.stem for p in WORKFLOWS.glob('*.json')) == ['poster-batch-submit', 'poster-error', 'poster-job-finished']
    for name in ('poster-batch-submit', 'poster-error', 'poster-job-finished'):
        assert load(name)['id'] == name


def test_job_finished_verifies_the_signature_before_responding() -> None:
    flow = load('poster-job-finished')
    webhook = next(n for n in flow['nodes'] if n['type'] == 'n8n-nodes-base.webhook')
    assert webhook['parameters']['path'] == 'poster-job-finished'
    assert webhook['parameters']['responseMode'] == 'responseNode'
    assert webhook['parameters']['options']['rawBody'] is True
    code = next(n for n in flow['nodes'] if n['name'] == '驗證簽章')['parameters']['jsCode']
    for needle in ('X-Webhook-Signature'.lower(), 'x-webhook-timestamp', 'timingSafeEqual', 'JOB_WEBHOOK_SECRET', '300'):
        assert needle in code
    assert {'n8n-nodes-base.respondToWebhook', 'n8n-nodes-base.wait', 'n8n-nodes-base.httpRequest',
            'n8n-nodes-base.googleSheets'} <= node_types(flow)
    assert flow['settings']['errorWorkflow'] == 'poster-error'


def test_batch_submit_calls_the_automation_api() -> None:
    flow = load('poster-batch-submit')
    urls = [n['parameters'].get('url', '') for n in flow['nodes'] if n['type'] == 'n8n-nodes-base.httpRequest']
    assert any('/api/automation/jobs' in u for u in urls)
    assert {'n8n-nodes-base.scheduleTrigger', 'n8n-nodes-base.googleSheets'} <= node_types(flow)
    assert flow['settings']['errorWorkflow'] == 'poster-error'


@pytest.mark.parametrize('path', sorted(WORKFLOWS.glob('*.json')), ids=lambda p: p.stem)
def test_no_credentials_or_secrets_are_committed(path: Path) -> None:
    text = path.read_text(encoding='utf-8')
    flow = json.loads(text)
    for node in flow['nodes']:
        for credential in node.get('credentials', {}).values():
            assert credential.get('id') in (None, ''), f'{node["name"]} 帶著憑證 id'
    assert 'discord.com/api/webhooks/' not in text
    assert 'Bearer ' + 't' * 8 not in text
```

- [ ] **Step 2：確認失敗**

Run: `uv run pytest tests/test_n8n_workflows.py -v`
Expected: FAIL（找不到 `n8n/workflows`）

- [ ] **Step 3：compose**

`docker-compose.yml`：

1. 在 `x-backend.environment` 加入（放在 `COMFYUI_WORKFLOWS_DIR` 之後）：

```yaml
    # 容器之間以 http://api:8000 呼叫（n8n 不經過 nginx）：Host 為 api 也要接受
    ALLOWED_HOSTS: '["127.0.0.1", "localhost", "api"]'
```

2. 在 `web` 服務之後加入兩個服務：

```yaml
  # 建立 n8n 的資料庫（已經初始化過的 postgres volume 不會再跑初始化腳本，所以每次啟動時檢查）
  n8n-db:
    profiles: [automation]
    image: public.ecr.aws/docker/library/postgres:18-alpine
    environment:
      PGPASSWORD: genai
    command:
      - sh
      - -c
      - psql -h postgres -U genai -d genai -tAc "SELECT 1 FROM pg_database WHERE datname = 'n8n'" | grep -q 1 || psql -h postgres -U genai -d genai -c 'CREATE DATABASE n8n'
    depends_on:
      postgres: { condition: service_healthy }
    restart: 'no'

  # n8n：試算表批次產圖與 Discord 審核（docker compose --profile automation up -d）。只綁 127.0.0.1:5678；
  # 第一次啟動時匯入 n8n/workflows/，之後的更新見 n8n/README.md。映像檔內建 node 使用者（非 root）
  n8n:
    profiles: [automation]
    image: docker.n8n.io/n8nio/n8n:<Step 4 決定的版本>
    ports: ['127.0.0.1:5678:5678']
    environment:
      DB_TYPE: postgresdb
      DB_POSTGRESDB_HOST: postgres
      DB_POSTGRESDB_DATABASE: n8n
      DB_POSTGRESDB_USER: genai
      DB_POSTGRESDB_PASSWORD: genai
      N8N_ENCRYPTION_KEY: ${N8N_ENCRYPTION_KEY:?請在 .env 設定 N8N_ENCRYPTION_KEY}
      GENERIC_TIMEZONE: Asia/Taipei
      TZ: Asia/Taipei
      # 審核表單與 webhook 的對外網址（Discord 訊息裡的表單連結）
      WEBHOOK_URL: http://127.0.0.1:5678/
      N8N_DIAGNOSTICS_ENABLED: 'false'
      N8N_PERSONALIZATION_ENABLED: 'false'
      # Code 節點驗簽要用 crypto；工作流以 $env 讀下面的變數
      NODE_FUNCTION_ALLOW_BUILTIN: crypto
      N8N_BLOCK_ENV_ACCESS_IN_NODE: 'false'
      AUTOMATION_API_URL: http://api:8000
      AUTOMATION_TOKEN: ${AUTOMATION_TOKEN:?請在 .env 設定 AUTOMATION_TOKEN}
      JOB_WEBHOOK_SECRET: ${JOB_WEBHOOK_SECRET:?請在 .env 設定 JOB_WEBHOOK_SECRET}
      DISCORD_WEBHOOK_URL: ${DISCORD_WEBHOOK_URL:-}
      GOOGLE_SHEET_ID: ${GOOGLE_SHEET_ID:-}
    entrypoint: ['sh', '-c']
    command:
      - '[ -f /home/node/.n8n/.imported ] || (n8n import:workflow --separate --input=/workflows && touch /home/node/.n8n/.imported); exec n8n start'
    volumes:
      - ./n8n/workflows:/workflows:ro
      - n8n:/home/node/.n8n
    depends_on:
      n8n-db: { condition: service_completed_successfully }
      api: { condition: service_healthy }
    restart: unless-stopped
```

3. `volumes:` 加上 `n8n:`。

4. api 與 worker 需要的 `JOB_WEBHOOK_URL`、`JOB_WEBHOOK_SECRET`、`AUTOMATION_TOKEN` 由 `.env`（`env_file`）傳入，不必在 compose 重複。

- [ ] **Step 4：決定 n8n 版本並確認 compose 有效**

Run: `docker run --rm docker.n8n.io/n8nio/n8n:latest --version`
Expected: 印出版本號（例如 `1.x.y` 或 `2.x.y`）。把這個版本號填進 `image: docker.n8n.io/n8nio/n8n:<版本>`（固定版本，不用 latest）。

Run: `docker compose --profile automation config --quiet`（`.env` 先填好 Step 5 的三個必填變數）
Expected: 沒有輸出、結束代碼 0

- [ ] **Step 5：`.env.example`**

檔案最後加入：

```bash
# ---------- 自動化（n8n，docker compose --profile automation up -d） ----------
# n8n 呼叫 /api/automation/* 用的 token（至少 32 字元）；空白為停用。產生方式：
#   python -c "import secrets; print(secrets.token_urlsafe(32))"
# AUTOMATION_TOKEN=
# 任務結束時通知 n8n；空白為不通知。JOB_WEBHOOK_SECRET 是簽章金鑰（至少 32 字元），n8n 用同一個值驗證
# JOB_WEBHOOK_URL=http://n8n:5678/webhook/poster-job-finished
# JOB_WEBHOOK_SECRET=
# webhook 的 Studio 連結前綴
# STUDIO_BASE_URL=http://127.0.0.1:3000
# 自動化建任務的預設模板（JSON 陣列）與每個模板的候選張數
# AUTOMATION_TEMPLATES=["ig-post", "story", "ecom-main"]
# AUTOMATION_VARIANTS=2
# n8n 加密憑證用的金鑰（設定後不要更改，否則 n8n 讀不到已儲存的憑證）
# N8N_ENCRYPTION_KEY=
# Discord 頻道的 webhook 網址（頻道設定 → 整合 → Webhook）與 Google Sheet 的 id（網址 /d/ 與 /edit 之間）
# DISCORD_WEBHOOK_URL=
# GOOGLE_SHEET_ID=
```

- [ ] **Step 6：在 n8n 介面建立三條工作流並匯出**

依下表在 `http://127.0.0.1:5678` 建立（先以 `docker compose --profile automation up -d` 啟動，第一次開啟時建立擁有者帳號）。完成後以 `docker compose exec n8n n8n export:workflow --all --separate --output=/tmp/wf` 匯出，再用 `docker compose cp n8n:/tmp/wf/. n8n/workflows/` 複製出來，**把檔名與 JSON 的 `id` 改成固定的** `poster-batch-submit`、`poster-job-finished`、`poster-error`，把每個節點 `credentials` 裡的 `id` 改成空字串（保留 `name`，匯入後由使用者在介面重新選擇）。

**`poster-error`**（Settings → Error workflow 給另外兩條使用）

| 節點 | 類型 | 設定 |
|---|---|---|
| Error Trigger | `n8n-nodes-base.errorTrigger` | — |
| 通知 Discord | `n8n-nodes-base.httpRequest` | POST `={{ $env.DISCORD_WEBHOOK_URL }}`，JSON body：`{"content": "⚠️ n8n 工作流「{{ $json.workflow.name }}」失敗：{{ $json.execution.lastNodeExecuted }}：{{ $json.execution.error.message }}"}` |

**`poster-batch-submit`**

| 節點 | 類型 | 設定 |
|---|---|---|
| 每 5 分鐘 | `n8n-nodes-base.scheduleTrigger` | interval 5 minutes |
| 讀取待處理的列 | `n8n-nodes-base.googleSheets` | 文件 `={{ $env.GOOGLE_SHEET_ID }}`、工作表 `需求`；Read rows；filter：`status` 為空 |
| 逐列 | `n8n-nodes-base.splitInBatches` | batch size 1 |
| 建立任務 | `n8n-nodes-base.httpRequest` | POST `={{ $env.AUTOMATION_API_URL }}/api/automation/jobs`；header `Authorization: Bearer {{ $env.AUTOMATION_TOKEN }}`；JSON body `{"brandId": "{{ $json.brand }}", "productId": "{{ $json.product }}", "brief": "{{ $json.brief }}", "clientRef": "sheet:{{ $env.GOOGLE_SHEET_ID }}:row:{{ $json.row_number }}"}`；Options → Response → Never Error（4xx／5xx 不中斷整批） |
| 成功？ | `n8n-nodes-base.if` | `={{ $json.jobId }}` is not empty |
| 標記排隊中 | `n8n-nodes-base.googleSheets` | Update row（以 `row_number` 比對）：`status=queued`、`jobId={{ $json.jobId }}` |
| 標記錯誤 | `n8n-nodes-base.googleSheets` | Update row：`status=error`、`message={{ $json.error.message }}` |

兩個「標記」節點都接回「逐列」，處理下一列。

**`poster-job-finished`**

| 節點 | 類型 | 設定 |
|---|---|---|
| 收到通知 | `n8n-nodes-base.webhook` | POST、path `poster-job-finished`、Respond：Using 'Respond to Webhook' Node（`responseMode: responseNode`）、Options → Raw Body 開啟 |
| 驗證簽章 | `n8n-nodes-base.code` | 程式碼見下方 |
| 有效？ | `n8n-nodes-base.if` | `={{ $json.valid }}` is true |
| 回覆 401 | `n8n-nodes-base.respondToWebhook` | status 401，body `={{ $json.reason }}` |
| 回覆 200 | `n8n-nodes-base.respondToWebhook` | status 200，body `ok` |
| 重複？ | `n8n-nodes-base.if` | `={{ $json.duplicate }}` is true → 結束（不接任何節點） |
| 來自試算表？ | `n8n-nodes-base.if` | `={{ ($json.payload.clientRef || '').startsWith('sheet:') }}` |
| 回填試算表 | `n8n-nodes-base.googleSheets` | Update row：row number 取 `={{ $json.payload.clientRef.split(':row:')[1] }}`；`status={{ $json.payload.stage }}`、`score={{ $json.payload.best?.score ?? '' }}`、`posterUrl={{ $json.payload.studioUrl }}`、`message={{ $json.payload.reason ?? $json.payload.failedChecks.map(c => c.name).join('、') }}` |
| 需要審核？ | `n8n-nodes-base.if` | `={{ ['done','needs_review'].includes($json.payload.stage) && $json.payload.best }}` |
| 下載海報 | `n8n-nodes-base.httpRequest` | GET `={{ $env.AUTOMATION_API_URL }}{{ $json.payload.best.imageUrl }}`，Response format File；`imageUrl` 為 null 時（REVIEW_MODE=sim）跳過這個節點，改走不附圖的分支 |
| 通知 Discord | `n8n-nodes-base.httpRequest` | POST `={{ $env.DISCORD_WEBHOOK_URL }}`，multipart：`payload_json`（`content` 內含品牌、需求、分數、未通過的檢查、`studioUrl`、審核表單網址 `{{ $execution.resumeFormUrl }}`，以及每張候選的 `renderId` 與分數）＋檔案欄位 `files[0]` |
| 等待審核 | `n8n-nodes-base.wait` | Resume：On Form Submitted；表單欄位：`決定`（dropdown：核准、退回，必填）、`候選圖`（text，選填，空白為最高分）、`修改意見`（textarea，選填）；Limit wait time：7 天 |
| 核准？ | `n8n-nodes-base.if` | `={{ $json['決定'] === '核准' }}` |
| 核准 | `n8n-nodes-base.httpRequest` | POST `={{ $env.AUTOMATION_API_URL }}/api/automation/jobs/{{ $('驗證簽章').item.json.payload.jobId }}/approve`；header Authorization 與 `Idempotency-Key: {{ $('驗證簽章').item.json.payload.webhookId }}:approve`；body `{"renderId": {{ $json['候選圖'] ? JSON.stringify($json['候選圖']) : 'null' }}}` |
| 退回 | `n8n-nodes-base.httpRequest` | POST `.../revise`；`Idempotency-Key: ...:revise`；body `{"feedback": {{ JSON.stringify($json['修改意見'] || '請重新生成') }}}`；Never Error |
| 回覆結果 | `n8n-nodes-base.httpRequest` | POST Discord：核准 → 「已選定 {{renderId}}」；退回成功 → 「已退回，新任務 {{jobId}}」；退回 409 → 回應的 `error.message` |

「驗證簽章」的程式碼（Mode：Run Once for All Items）：

```javascript
const crypto = require('crypto');
const item = $input.first();
const h = item.json.headers;
const raw = await this.helpers.getBinaryDataBuffer(0, 'data');
const timestamp = Number(h['x-webhook-timestamp']);
const given = String(h['x-webhook-signature'] || '');
const expected = 'v1=' + crypto.createHmac('sha256', $env.JOB_WEBHOOK_SECRET)
  .update(Buffer.concat([Buffer.from(`${timestamp}.`), raw]))
  .digest('hex');
const fresh = Number.isFinite(timestamp) && Math.abs(Date.now() / 1000 - timestamp) <= 300;
const same = given.length === expected.length &&
  crypto.timingSafeEqual(Buffer.from(given), Buffer.from(expected));
if (!fresh || !same) {
  return [{ json: { valid: false, reason: fresh ? 'bad signature' : 'stale timestamp' } }];
}
const id = String(h['x-webhook-id']);
const seen = $getWorkflowStaticData('global');
seen.ids = seen.ids || [];
const duplicate = seen.ids.includes(id);
if (!duplicate) {
  seen.ids.push(id);
  if (seen.ids.length > 1000) seen.ids.splice(0, seen.ids.length - 1000);
}
return [{ json: { valid: true, duplicate, payload: JSON.parse(raw.toString('utf8')) } }];
```

（`x-webhook-signature` 以小寫出現在程式碼裡，Step 1 的測試據此檢查。）

兩條主要工作流的 Settings → Error workflow 都選 `poster-error`（匯出後 `settings.errorWorkflow` 為 `poster-error`；若匯出的是內部數字 id，手動改成 `poster-error`）。

- [ ] **Step 7：`n8n/README.md`**

內容包含以下各節（全部繁體中文）：

1. **用途**：兩條工作流做什麼（引用規格 §5），以及一張與規格 §4 相同的流程圖。
2. **啟動**：`.env` 必填的 `AUTOMATION_TOKEN`、`JOB_WEBHOOK_URL`、`JOB_WEBHOOK_SECRET`、`N8N_ENCRYPTION_KEY`（附產生指令）；`docker compose --profile automation up -d`；第一次開啟 `http://127.0.0.1:5678` 建立擁有者帳號。
3. **憑證**：Google Sheets OAuth2（在 Google Cloud 建立 OAuth 用戶端，重新導向 URI 為 `http://127.0.0.1:5678/rest/oauth2-credential/callback`），在三個 Google Sheets 節點選擇該憑證；Discord 只需要 `.env` 的 `DISCORD_WEBHOOK_URL`。
4. **試算表格式**：工作表 `需求`，第一列為 `brand`、`product`、`brief`、`status`、`jobId`、`score`、`posterUrl`、`message`。
5. **啟用**：在介面把 `poster-batch-submit` 與 `poster-job-finished` 切成 Active。
6. **更新工作流**：repo 的 JSON 改了之後執行
   `docker compose exec n8n n8n import:workflow --separate --input=/workflows`
   （會覆蓋同 id 的工作流與啟用狀態，之後重新啟用）；介面上的修改以 Step 6 的匯出方式存回 repo。
7. **已知限制**：審核表單只有本機或同一個區網打得開；`REVIEW_MODE=sim` 時 Discord 訊息不附圖。

- [ ] **Step 8：確認測試通過**

Run: `uv run pytest tests/test_n8n_workflows.py -v`
Expected: PASS

- [ ] **Step 9：Commit**

```bash
git add docker-compose.yml .env.example n8n backend/tests/test_n8n_workflows.py
git commit -m "feat: add n8n to compose with batch submit and Discord review workflows"
```

---

### Task 10：live 驗收、文件與實驗結果

**Files:**
- Create: `backend/tests/test_automation_live.py`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-11-05-plan9-n8n-automation-design.md`（新增 §14 實驗結果、更新狀態）

**Interfaces:**
- Consumes: 執行中的 compose（含 `automation` profile）、Task 1–9 的全部功能

- [ ] **Step 1：live 測試** `backend/tests/test_automation_live.py`

```python
"""live：對執行中的 docker compose（--profile automation、AGENT_MODE=sim、IMAGE_MODE=sim）跑一輪
「建任務 → webhook 送達 n8n → 核准」與「退回 → 新任務 → webhook」。需要 .env 的 AUTOMATION_TOKEN，
以及在 n8n 啟用 poster-job-finished。手動執行：uv run pytest -m live tests/test_automation_live.py"""

import asyncio
import os

import httpx
import pytest
from sqlalchemy import select

from app.db.models import WebhookOutboxRow
from app.db.session import Database
from app.settings import Settings

pytestmark = pytest.mark.live

API = 'http://127.0.0.1:8000'
BRIEF = {'brandId': 'selune', 'productId': 'prod_selune_serum', 'brief': '週年慶主打買一送一，要溫柔療癒的感覺',
         'templateIds': ['story'], 'variantsPerTemplate': 1}


async def wait_delivered(db: Database, job_id: str, timeout: float = 120) -> WebhookOutboxRow:
    async with asyncio.timeout(timeout):
        while True:
            async with db.session() as s:
                row = await s.scalar(select(WebhookOutboxRow).where(WebhookOutboxRow.job_id == job_id))
            if row is not None and row.status != 'pending':
                return row
            await asyncio.sleep(2)


async def test_job_webhook_reaches_n8n_and_approve_and_revise_work() -> None:
    settings = Settings()
    token = settings.automation_token.get_secret_value() or os.environ['AUTOMATION_TOKEN']
    auth = {'Authorization': f'Bearer {token}'}
    db = Database(settings.database_url)
    try:
        async with httpx.AsyncClient(base_url=API, headers=auth, timeout=60) as http:
            job_id = (await http.post('/api/automation/jobs', json=BRIEF)).raise_for_status().json()['jobId']
            row = await wait_delivered(db, job_id)
            assert row.status == 'delivered', row.last_error
            res = await http.post(f'/api/automation/jobs/{job_id}/approve', json={}, headers={'Idempotency-Key': f'{row.id}:approve'})
            assert res.status_code == 201
            child = (await http.post(f'/api/automation/jobs/{job_id}/revise', json={'feedback': '標題改成限時三天'})).json()['jobId']
            child_row = await wait_delivered(db, child)
            assert child_row.status == 'delivered'
            assert child_row.payload['parentJobId'] == job_id
            snap = (await http.get(f'/api/jobs/{child}')).json()
            assert any(e['type'] == 'log' and '審核者退回' in e['message'] for e in snap['events'])
    finally:
        await db.dispose()
```

- [ ] **Step 2：執行 live 驗收（規格 §10）**

1. `.env` 設定 `AGENT_MODE=sim`、`IMAGE_MODE=sim`、`REVIEW_MODE=composer`，以及 Task 9 的自動化變數；`docker compose --profile automation up -d --build --wait`。
2. 在 n8n 設定 Google Sheets 憑證、啟用兩條工作流。
3. Run: `uv run pytest -m live tests/test_automation_live.py -v` → Expected: PASS
4. 依規格 §10 逐項手動確認並記錄結果：
   - (1) 工作流自動匯入；
   - (2) Sheet 3 列需求 5 分鐘內變成 `queued`，結束後回填；
   - (3) Discord 收到附圖訊息，表單核准後 Studio 的歷史紀錄出現、`writtenToRag` 為 true；
   - (4) 退回後新任務的 Agent 透視有「審核者退回」log；
   - (5) `docker compose stop n8n` → 跑完一個任務 → `docker compose start n8n`：通知在退避時間內補送，n8n 只處理一次（看 n8n 的執行紀錄）；
   - (6) 以 curl 送一個簽章錯誤的請求到 `http://127.0.0.1:5678/webhook/poster-job-finished`，回 401；
   - (7) `docker compose up -d`（不含 profile）時 `docker stats` 的記憶體用量與先前相同，n8n 不在執行。
5. 量 n8n 閒置與執行中的記憶體（`docker stats --no-stream`）。

- [ ] **Step 3：把結果寫進規格**

規格最上方的狀態改為「已實作（2026-11-xx）」，最後新增：

```markdown
## 14. 實驗結果

### §10 的驗收（日期、環境：Docker Desktop＋WSL 2 記憶體上限、n8n 版本）

| 項目 | 結果 |
|---|---|
| (1)–(7) | 每一項的實際結果與觀察到的數字 |
| n8n 記憶體 | 閒置與執行中 |
```

（以 Step 2 的實際結果填寫，不得留空；某項不通過時寫出原因與處理方式。）

- [ ] **Step 4：README**

`README.md` 的「技術重點 → 可靠性與安全」之後新增一節：

```markdown
### 自動化整合（n8n）

- **試算表批次產圖**：n8n 讀 Google Sheet 的每一列，以 token 呼叫 `/api/automation/jobs`；任務結束後回填分數與連結。
- **Discord 審核**：結束通知附上審查用海報與合規分數，審核者在 n8n 表單核准（寫入歷史並回寫 RAG）或退回並附意見（意見進入 RAG 查詢、Prompt 構建與價格護欄）。
- **不漏送的 webhook**：通知與任務的結束事件在同一個 PostgreSQL 交易內寫入 outbox；worker 以 `FOR UPDATE SKIP LOCKED` 發送、HMAC-SHA256 簽章、依退避表重試 8 次，接收端依 id 去重；核准與退回支援 Idempotency-Key。
```

並在「架構」的 mermaid 圖加上 `n8n` 節點（`n8n -- token --> api`、`worker -- webhook --> n8n`），在「快速開始」最後加一行：`自動化整合：見 [n8n/README.md](n8n/README.md)`。放一張 n8n 工作流的截圖與一張 Discord 審核訊息的截圖到 `docs/images/`（`n8n-workflow.png`、`discord-review.png`），在該節引用。依 README 偏好：不提及 AI 協助。

- [ ] **Step 5：全部檢查**

Run（`backend/`）：`uv run pytest && uv run mypy app tests && uv run ruff check . && uv run ruff format --check .`
Run（`web/`，Task 8 有改前端時）：`npm test && npm run typecheck && npm run lint`
Expected: 全部 PASS

- [ ] **Step 6：Commit**

```bash
git add backend/tests/test_automation_live.py README.md docs
git commit -m "docs: record the n8n automation acceptance results and document the integration"
```
