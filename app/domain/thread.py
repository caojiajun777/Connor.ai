"""Long-term intelligence thread schemas."""

from typing import Any

from pydantic import Field, model_validator

from app.domain.base import AwareDatetime, ConnorBaseModel, DomainModel, NonEmptyStr
from app.domain.enums import ConfidenceLevel, LaterOutcome, PriorityLevel, ThreadStatus


class ThreadTimelineEntry(ConnorBaseModel):
    """An event in a long-term intelligence logic chain."""

    event_at: AwareDatetime
    summary: NonEmptyStr
    confidence_at_time: ConfidenceLevel
    later_outcome: LaterOutcome = LaterOutcome.PENDING
    cluster_id: str | None = None
    watchlist_id: str | None = None
    archive_id: str | None = None
    report_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_linked_object(self) -> "ThreadTimelineEntry":
        if not any([self.cluster_id, self.watchlist_id, self.archive_id, self.report_id]):
            raise ValueError("thread timeline entries require at least one linked object id")
        return self


class IntelligenceThread(DomainModel):
    """A long-running logic chain connecting signals, archives, and later outcomes."""

    title: NonEmptyStr
    status: ThreadStatus = ThreadStatus.ACTIVE
    importance: PriorityLevel = PriorityLevel.MEDIUM
    entities: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    current_thesis: NonEmptyStr
    timeline: list[ThreadTimelineEntry] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    linked_cluster_ids: list[str] = Field(default_factory=list)
    linked_watchlist_ids: list[str] = Field(default_factory=list)
    linked_archive_ids: list[str] = Field(default_factory=list)
    linked_report_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_thread_timeline(self) -> "IntelligenceThread":
        if not self.timeline:
            raise ValueError("intelligence threads require at least one timeline entry")
        return self

