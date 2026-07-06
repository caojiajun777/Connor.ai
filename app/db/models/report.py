"""Daily report ORM model."""

from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import DomainPayloadMixin


class DailyReportRecord(DomainPayloadMixin, Base):
    __tablename__ = "daily_reports"
    __table_args__ = (
        CheckConstraint(
            "quality_score >= 0 AND quality_score <= 10",
            name="ck_daily_reports_quality_score_range",
        ),
    )

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    quality_score: Mapped[float | None] = mapped_column(nullable=True, index=True)

