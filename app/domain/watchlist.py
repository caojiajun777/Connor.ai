"""Watchlist and archive schemas."""

from typing import Any

from pydantic import Field, model_validator

from app.domain.base import AwareDatetime, ConnorBaseModel, DomainModel, NonEmptyStr, Probability
from app.domain.enums import ArchiveReason, PriorityLevel, WatchStatus, WatchTier


class WatchHistoryEntry(ConnorBaseModel):
    """A timeline entry for changes to a watch item."""

    at: AwareDatetime
    summary: NonEmptyStr
    evidence_ids: list[str] = Field(default_factory=list)


class WatchlistItem(DomainModel):
    """A cost-controlled active tracking item."""

    run_id: NonEmptyStr
    topic: NonEmptyStr
    thesis: NonEmptyStr
    watch_tier: WatchTier
    status: WatchStatus = WatchStatus.ACTIVE
    priority: PriorityLevel = PriorityLevel.MEDIUM
    ttl_days: int = Field(gt=0)
    watch_until: AwareDatetime
    revisit_cadence_days: int = Field(default=1, gt=0)
    last_checked_at: AwareDatetime | None = None
    last_signal_at: AwareDatetime | None = None
    decay_score: Probability = 0
    reactivation_rules: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    cluster_ids: list[str] = Field(default_factory=list)
    thread_id: str | None = None
    history: list[WatchHistoryEntry] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_watch_window(self) -> "WatchlistItem":
        if self.watch_until <= self.created_at:
            raise ValueError("watch_until must be later than created_at")

        if self.watch_tier == WatchTier.SHORT and self.ttl_days > 7:
            raise ValueError("short watch ttl_days must be <= 7")
        if self.watch_tier == WatchTier.EVENT and not (7 <= self.ttl_days <= 21):
            raise ValueError("event watch ttl_days must be between 7 and 21")
        if self.watch_tier == WatchTier.STRATEGIC and not (30 <= self.ttl_days <= 90):
            raise ValueError("strategic watch ttl_days must be between 30 and 90")

        if self.status == WatchStatus.ACTIVE and not self.reactivation_rules:
            raise ValueError("active watch items require reactivation_rules")

        return self


class ArchivedSignal(DomainModel):
    """An inactive signal preserved for future logic-chain analysis."""

    run_id: NonEmptyStr
    original_cluster_id: str | None = None
    original_watchlist_id: str | None = None
    thread_id: str | None = None
    archive_reason: ArchiveReason
    archived_at: AwareDatetime
    final_state: NonEmptyStr
    reactivation_hint: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_archive_lineage(self) -> "ArchivedSignal":
        if not any([self.original_cluster_id, self.original_watchlist_id]):
            raise ValueError("archived signals require original_cluster_id or original_watchlist_id")
        return self

