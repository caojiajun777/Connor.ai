"""ReportEvaluation ORM record."""

from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import DomainPayloadMixin


class ReportEvaluationRecord(DomainPayloadMixin, Base):
    __tablename__ = "report_evaluations"

    report_id: Mapped[str] = mapped_column(index=True)
    run_id: Mapped[str] = mapped_column(index=True)
