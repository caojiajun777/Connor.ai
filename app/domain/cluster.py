"""Event cluster schemas."""

from typing import Any

from pydantic import Field, field_validator, model_validator

from app.domain.base import AwareDatetime, ConnorBaseModel, DomainModel, NonEmptyStr, normalize_unique
from app.domain.enums import CandidateCategory


class ClusterTimelineEntry(ConnorBaseModel):
    """A dated observation inside an event cluster."""

    observed_at: AwareDatetime
    summary: NonEmptyStr
    evidence_ids: list[str] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)

    @field_validator("evidence_ids", "candidate_ids")
    @classmethod
    def values_must_be_unique(cls, value: list[str]) -> list[str]:
        return normalize_unique(value)


class EventCluster(DomainModel):
    """A deduplicated event-level claim composed from candidates and evidence."""

    run_id: NonEmptyStr
    category: CandidateCategory
    title: NonEmptyStr
    canonical_claim: NonEmptyStr
    candidate_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    tickers: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    timeline: list[ClusterTimelineEntry] = Field(default_factory=list)
    conflict_summary: str | None = None
    dedupe_key: NonEmptyStr
    selected: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("candidate_ids", "evidence_ids", "entities", "tickers", "topics")
    @classmethod
    def values_must_be_unique(cls, value: list[str]) -> list[str]:
        return normalize_unique(value)

    @model_validator(mode="after")
    def validate_cluster_lineage(self) -> "EventCluster":
        if not self.candidate_ids:
            raise ValueError("event clusters require candidate_ids")
        if not self.evidence_ids:
            raise ValueError("event clusters require evidence_ids")
        if not self.timeline:
            raise ValueError("event clusters require at least one timeline entry")
        return self

