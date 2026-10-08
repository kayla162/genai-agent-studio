"""資料表：合約物件整份存成 JSONB（data），另外拆出查詢用的欄位。"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Json = dict[str, Any]


class Base(DeclarativeBase):
    type_annotation_map = {Json: JSONB, datetime: DateTime(timezone=True)}


class BrandRow(Base):
    """品牌設定檔匯入的內容（guidelineChunks 另存在 brand_chunks）。"""

    __tablename__ = 'brands'

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str]
    config: Mapped[Json]
    source_hash: Mapped[str]
    #: 設定檔已移除的品牌保留資料列（任務與歷史紀錄仍會參照），但不再列出
    active: Mapped[bool] = mapped_column(Boolean, server_default=false())
    updated_at: Mapped[datetime]


class BrandChunkRow(Base):
    """RAG 切塊。origin：config（設定檔）、alt（合規替代用語）、upload（上傳的手冊）、history（選定海報回寫）。"""

    __tablename__ = 'brand_chunks'

    id: Mapped[str] = mapped_column(String, primary_key=True)
    brand_id: Mapped[str] = mapped_column(ForeignKey('brands.id', ondelete='CASCADE'), index=True)
    source: Mapped[str]
    section: Mapped[str]
    tag: Mapped[str]
    text: Mapped[str] = mapped_column(Text)
    origin: Mapped[str]
    #: 同一來源內的順序
    position: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime]


class ProductRow(Base):
    __tablename__ = 'products'

    id: Mapped[str] = mapped_column(String, primary_key=True)
    brand_id: Mapped[str] = mapped_column(ForeignKey('brands.id'), index=True)
    data: Mapped[Json]
    #: 品牌設定檔的示範商品；刪除時只標記 deleted，重新匯入設定檔也不會加回
    sample: Mapped[bool] = mapped_column(Boolean, server_default=false())
    deleted: Mapped[bool] = mapped_column(Boolean, server_default=false())
    created_at: Mapped[datetime]


class JobRow(Base):
    __tablename__ = 'jobs'

    id: Mapped[str] = mapped_column(String, primary_key=True)
    brand_id: Mapped[str] = mapped_column(String, index=True)
    input: Mapped[Json]
    created_at: Mapped[datetime] = mapped_column(index=True)
    stage: Mapped[str]
    round: Mapped[int] = mapped_column(Integer, server_default='0')
    finished: Mapped[bool] = mapped_column(Boolean, server_default=false())
    best_render_ids: Mapped[Json] = mapped_column(server_default='{}')
    #: 最後一則事件的序號（新增事件時在同一交易內加 1）
    last_seq: Mapped[int] = mapped_column(Integer, server_default='0')
    cancel_requested: Mapped[bool] = mapped_column(Boolean, server_default=false())
    failure_reason: Mapped[str | None] = mapped_column(Text)


class JobEventRow(Base):
    __tablename__ = 'job_events'

    job_id: Mapped[str] = mapped_column(ForeignKey('jobs.id', ondelete='CASCADE'), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime]
    type: Mapped[str]
    #: 事件 JSON（不含 seq、ts）
    payload: Mapped[Json]


class HistoryRow(Base):
    __tablename__ = 'history'

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey('jobs.id', ondelete='CASCADE'))
    brand_id: Mapped[str] = mapped_column(String, index=True)
    data: Mapped[Json]
    selected_at: Mapped[datetime] = mapped_column(index=True)
