"""Artifact ORM model."""

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import DomainPayloadMixin


class ArtifactRecord(DomainPayloadMixin, Base):
    __tablename__ = "artifacts"

    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    size_bytes: Mapped[int | None] = mapped_column(nullable=True)

