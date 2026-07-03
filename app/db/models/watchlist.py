"""Watchlist and archive ORM models."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import DomainPayloadMixin


class WatchlistItemRecord(DomainPayloadMixin, Base):
    __tablename__ = "watchlist_items"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    watch_tier: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ttl_days: Mapped[int] = mapped_column(nullable=False)
    watch_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_signal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    thread_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)


class ArchivedSignalRecord(DomainPayloadMixin, Base):
    __tablename__ = "archived_signals"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    original_cluster_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    original_watchlist_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    thread_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    archive_reason: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    final_state: Mapped[str] = mapped_column(Text, nullable=False)

