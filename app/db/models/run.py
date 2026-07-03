"""Run ORM model."""

from datetime import date
from typing import Any

from sqlalchemy import Date, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import DomainPayloadMixin


class RunRecord(DomainPayloadMixin, Base):
    __tablename__ = "runs"

    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    phase: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

