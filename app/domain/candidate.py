"""Candidate intelligence item schemas."""

from typing import Any

from pydantic import Field, field_validator, model_validator

from app.domain.base import DomainModel, NonEmptyStr, normalize_unique
from app.domain.enums import (
    AgentRole,
    CandidateCategory,
    ConfidenceLevel,
    EvidenceStrength,
    SignalStatus,
)


EARLY_SIGNAL_STATUSES = {
    SignalStatus.UNCONFIRMED_LEAK,
    SignalStatus.GRAY_ROLLOUT_FEEDBACK,
    SignalStatus.CODE_ANOMALY,
    SignalStatus.RESEARCHER_HINT,
    SignalStatus.COMMUNITY_RUMOR,
    SignalStatus.SINGLE_SOURCE_SIGNAL,
    SignalStatus.MANUAL_HYPOTHESIS,
}


class CandidateItem(DomainModel):
    """A scout-produced candidate claim before dedupe, clustering, and evaluation."""

    run_id: NonEmptyStr
    category: CandidateCategory
    signal_status: SignalStatus | None = None
    claim_summary: NonEmptyStr
    entities: list[str] = Field(default_factory=list)
    tickers: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    source_candidate_ids: list[str] = Field(default_factory=list)
    uncertainty: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    evidence_strength: EvidenceStrength = EvidenceStrength.UNKNOWN
    why_it_matters: str | None = None
    potential_impact: str | None = None
    followup_questions: list[str] = Field(default_factory=list)
    created_by_agent: AgentRole
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("entities", "tickers", "topics", "evidence_ids", "source_candidate_ids")
    @classmethod
    def values_must_be_unique(cls, value: list[str]) -> list[str]:
        return normalize_unique(value)

    @model_validator(mode="after")
    def validate_candidate_rules(self) -> "CandidateItem":
        if not self.evidence_ids and self.signal_status != SignalStatus.MANUAL_HYPOTHESIS:
            raise ValueError("candidate requires evidence_ids unless it is a manual hypothesis")

        if self.category == CandidateCategory.EARLY_SIGNAL:
            if self.signal_status not in EARLY_SIGNAL_STATUSES:
                raise ValueError("early signals require a non-confirmed signal_status")
            if not self.followup_questions:
                raise ValueError("early signals require followup_questions")

        if self.category == CandidateCategory.CONFIRMED_EVENT:
            if self.evidence_strength not in {EvidenceStrength.STRONG, EvidenceStrength.OFFICIAL}:
                raise ValueError("confirmed events require strong or official evidence")
            if self.signal_status not in {
                None,
                SignalStatus.OFFICIAL_CONFIRMATION,
                SignalStatus.CONFIRMED_FACT,
                SignalStatus.NOT_APPLICABLE,
            }:
                raise ValueError("confirmed events cannot use unconfirmed signal statuses")

        return self

