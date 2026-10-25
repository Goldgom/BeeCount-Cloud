"""Cloud-only immutable finance journal; deliberately not a mobile sync entity."""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .models import Base, utcnow


class FinanceEvent(Base):
    __tablename__ = "finance_events"
    __table_args__ = (UniqueConstraint("user_id", "request_key", name="uq_finance_request"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    request_key: Mapped[str] = mapped_column(String(255))
    request_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(40), index=True)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    payload: Mapped[dict] = mapped_column(JSON)
    # Signed Decimal strings in account currency. Never income/expense projections.
    effects: Mapped[dict] = mapped_column(JSON, default=dict)
