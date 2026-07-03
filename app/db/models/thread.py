"""Intelligence thread ORM model."""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import DomainPayloadMixin


class IntelligenceThreadRecord(DomainPayloadMixin, Base):
    __tablename__ = "intelligence_threads"

    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    importance: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    current_thesis: Mapped[str] = mapped_column(Text, nullable=False)

