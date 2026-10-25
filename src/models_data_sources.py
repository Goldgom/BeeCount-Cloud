"""Cloud-only read-only integrations; never mobile projections or initial balances."""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, Integer, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .models import Base, utcnow


class DataSource(Base):
    __tablename__ = 'data_sources'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(32), default='binance_api')
    credentials_encrypted: Mapped[str] = mapped_column(Text)
    account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    coverage_policy: Mapped[str] = mapped_column(String(32), default='separate')
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, default=300)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    symbols: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(24), default='never_synced')
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    cursors: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lock_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lock_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DataSourceEvent(Base):
    __tablename__ = 'data_source_events'
    __table_args__ = (UniqueConstraint('source_id', 'kind', 'external_id', name='uq_data_source_event'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_id: Mapped[str] = mapped_column(ForeignKey('data_sources.id', ondelete='CASCADE'), index=True)
    kind: Mapped[str] = mapped_column(String(80))
    external_id: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict] = mapped_column(JSON)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DataSourceSyncReceipt(Base):
    __tablename__ = 'data_source_sync_receipts'
    __table_args__ = (UniqueConstraint('source_id', 'request_key', name='uq_data_source_sync_key'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_id: Mapped[str] = mapped_column(ForeignKey('data_sources.id', ondelete='CASCADE'), index=True)
    request_key: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
