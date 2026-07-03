"""Structured output schemas for Connor.ai agents."""

from typing import Any

from pydantic import Field, model_validator

from app.domain.base import ConnorBaseModel, NonEmptyStr
from app.domain.enums import (
    CandidateCategory,
    ConfidenceLevel,
    EvaluationDecision,
    EvidenceStrength,
    ReviewDecision,
    SignalStatus,
)


class AgentStructuredOutput(ConnorBaseModel):
    """Base structured output every Connor.ai agent must provide."""

    summary: NonEmptyStr
    reasoning_summary: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)
    cluster_ids: list[str] = Field(default_factory=list)
    evaluation_ids: list[str] = Field(default_factory=list)
    watchlist_ids: list[str] = Field(default_factory=list)
    report_ids: list[str] = Field(default_factory=list)
    trace_event_ids: list[str] = Field(default_factory=list)
    followup_queries: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CandidateDraft(ConnorBaseModel):
    """Scout-proposed candidate content to be materialized by the harness."""

    category: CandidateCategory
    signal_status: SignalStatus | None = None
    claim_summary: NonEmptyStr
    entities: list[str] = Field(default_factory=list)
    tickers: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    uncertainty: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    evidence_strength: EvidenceStrength = EvidenceStrength.UNKNOWN
    why_it_matters: str | None = None
    potential_impact: str | None = None
    followup_questions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScoutOutput(AgentStructuredOutput):
    """Structured Scout output."""

    candidate_drafts: list[CandidateDraft] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scout_output(self) -> "ScoutOutput":
        if not (
            self.evidence_ids
            or self.candidate_ids
            or self.candidate_drafts
            or self.followup_queries
        ):
            raise ValueError(
                "scout output requires evidence, candidates, candidate drafts, or follow-up queries"
            )
        return self


class EvaluatorOutput(AgentStructuredOutput):
    """Structured Evaluator output."""

    decisions: list[EvaluationDecision] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_evaluator_output(self) -> "EvaluatorOutput":
        if not (self.evaluation_ids or self.decisions):
            raise ValueError("evaluator output requires evaluation_ids or decisions")
        return self


class WriterOutput(AgentStructuredOutput):
    """Structured Writer output."""

    markdown_preview: str | None = None

    @model_validator(mode="after")
    def validate_writer_output(self) -> "WriterOutput":
        if not self.report_ids:
            raise ValueError("writer output requires report_ids")
        return self


class ReviewerOutput(AgentStructuredOutput):
    """Structured Reviewer output."""

    review_result_ids: list[str] = Field(default_factory=list)
    decision: ReviewDecision
    required_changes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_reviewer_output(self) -> "ReviewerOutput":
        if self.decision != ReviewDecision.PASS and not self.required_changes:
            raise ValueError("non-pass reviewer output requires required_changes")
        return self


class EditorOutput(AgentStructuredOutput):
    """Structured Editor output."""

    edited_report_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_editor_output(self) -> "EditorOutput":
        if not self.edited_report_ids:
            raise ValueError("editor output requires edited_report_ids")
        return self
