"""Evaluation ORM model."""

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import DomainPayloadMixin


class EvaluationResultRecord(DomainPayloadMixin, Base):
    __tablename__ = "evaluation_results"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    cluster_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    evaluator_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_by_agent: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    total_score: Mapped[float] = mapped_column(nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reasoning_summary: Mapped[str] = mapped_column(Text, nullable=False)
    write_policy: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

