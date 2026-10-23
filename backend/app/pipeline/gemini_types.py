"""Gemini 的結構化輸出（response_json_schema 由這些模型產生）與 composer 護欄的結果。

SpecDraft、VlmVerdict、GuardIssue 對應 web/src/types/agent.ts，以 contracts/fixtures/agent.json 確認一致；
JSON 一律 camelCase。
這裡只限制結構（型別、項目數）；文案長度、缺字、禁用詞與版面規則由護欄處理，問題才能以中文說明帶回去重問。
"""

from typing import Literal

from pydantic import Field

from app.contract import CheckId, LayoutElementId, Model, Tone

VlmStatus = Literal['pass', 'warn', 'fail']
GuardCode = Literal[
    'emoji_removed',
    'missing_glyph',
    'banned_word',
    'too_long',
    'invented_offer',
    'empty_field',
    'product_glyph',
    'layout_invalid',
    'layout_rule',
    'text_too_small',
    'prompt_invalid',
]


class BriefDraft(Model):
    """需求拆解（POST /api/briefs/parse）。productName 由程式取自商品資料。"""

    selling_points: list[str] = Field(max_length=3)
    audience: str = Field(max_length=20)
    tone: Tone
    #: 需求有提到才填，否則為 null
    campaign: str | None
    offer: str | None
    period: str | None
    #: 英文小寫單字
    style: list[str] = Field(max_length=5)


class LayoutDraftBox(Model):
    id: LayoutElementId
    #: [x, y, w, h]（畫布像素）
    bbox: list[int] = Field(min_length=4, max_length=4)


class BadgeDraft(Model):
    top: str
    main: str
    sub: str


class SpecDraft(Model):
    """Prompt 構建：文案、版面與生圖場景。色票、售價、商品名稱、註記與圖層順序由程式決定。"""

    headline: list[str] = Field(min_length=2, max_length=2)
    subhead: str
    features: list[str] = Field(max_length=3)
    badge: BadgeDraft
    price_label: str
    #: 8 個元素各一個方框；不含 z
    layout: list[LayoutDraftBox] = Field(min_length=8, max_length=8)
    #: 英文的生圖場景描述
    scene: str = Field(max_length=300)
    #: 英文，加在負向提示詞後面
    negative_extra: str = Field(max_length=200)
    #: 一句中文，說明版面與文案的想法
    rationale: str


class FixDraft(Model):
    check_id: CheckId
    title: str
    desc: str


class RewriteDraft(Model):
    """Query Rewriting：每個未通過檢查的修正項，以及需要重新檢索合規用語時的查詢。"""

    fixes: list[FixDraft]
    requery: str | None


class Exaggeration(Model):
    status: VlmStatus
    phrases: list[str]
    reason: str


class Occlusion(Model):
    status: VlmStatus
    elements: list[LayoutElementId]
    reason: str


class Quality(Model):
    status: VlmStatus
    issues: list[str]
    reason: str


class VlmVerdict(Model):
    """VLM 審查：畫面上所有文字（依閱讀順序一行一筆；看不清楚的字為「?」，方塊為「□」）與三項判讀。"""

    lines: list[str]
    exaggeration: Exaggeration
    occlusion: Occlusion
    quality: Quality


class GuardIssue(Model):
    """composer 護欄發現的問題；retry 為 true 時 Agent 帶著 message 重問一次。"""

    code: GuardCode
    #: JSON 路徑，例如 headline.0、badge.main、layout、scene、productName
    field: str
    message: str
    retry: bool
