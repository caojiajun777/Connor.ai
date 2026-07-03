"""Review ORM models."""

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import DomainPayloadMixin


class ReviewResultRecord(DomainPayloadMixin, Base):
    __tablename__ = "review_results"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    report_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    reviewer_agent: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reasoning_summary: Mapped[str] = mapped_column(Text, nullable=False)


class ReviewIssueRecord(DomainPayloadMixin, Base):
    __tablename__ = "review_issues"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    report_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    report_item_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

