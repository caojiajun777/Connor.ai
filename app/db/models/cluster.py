"""Event cluster ORM model."""

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import DomainPayloadMixin


class EventClusterRecord(DomainPayloadMixin, Base):
    __tablename__ = "event_clusters"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_claim: Mapped[str] = mapped_column(Text, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

