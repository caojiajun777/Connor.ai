"""Candidate ORM model."""

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import DomainPayloadMixin


class CandidateItemRecord(DomainPayloadMixin, Base):
    __tablename__ = "candidate_items"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    signal_status: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    claim_summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_agent: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    uncertainty: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_strength: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

