"""Structured output schemas for Connor.ai agents."""

from typing import Any

from pydantic import Field, field_validator, model_validator

from app.domain.base import AwareDatetime, ConnorBaseModel, NonEmptyStr, Score, normalize_unique
from app.domain.enums import (
    ArchiveReason,
    CandidateCategory,
    ConfidenceLevel,
    EvaluationDecision,
    EvaluationType,
    EvidenceStrength,
    LaterOutcome,
    PriorityLevel,
    ReviewDecision,
    SignalStatus,
    ThreadStatus,
    WatchTier,
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


class ClusterTimelineDraft(ConnorBaseModel):
    """Clusterer-proposed timeline entry."""

    summary: NonEmptyStr
    evidence_ids: list[str] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)


class ClusterDraft(ConnorBaseModel):
    """Clusterer-proposed event cluster content."""

    category: CandidateCategory
    title: NonEmptyStr
    canonical_claim: NonEmptyStr
    candidate_ids: list[str]
    evidence_ids: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    tickers: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    timeline: list[ClusterTimelineDraft] = Field(default_factory=list)
    conflict_summary: str | None = None
    dedupe_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_cluster_draft(self) -> "ClusterDraft":
        if not self.candidate_ids:
            raise ValueError("cluster drafts require candidate_ids")
        return self


class ClustererOutput(AgentStructuredOutput):
    """Structured Clusterer output."""

    cluster_drafts: list[ClusterDraft] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_clusterer_output(self) -> "ClustererOutput":
        if not (self.cluster_ids or self.cluster_drafts):
            raise ValueError("clusterer output requires cluster_ids or cluster_drafts")
        return self


class EvaluationDraft(ConnorBaseModel):
    """Evaluator-proposed decision to be materialized by the harness."""

    cluster_id: NonEmptyStr
    evaluator_type: EvaluationType
    dimension_scores: dict[str, float]
    total_score: float
    decision: EvaluationDecision
    reasoning_summary: NonEmptyStr
    risk_flags: list[str] = Field(default_factory=list)
    required_followups: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_evaluation_draft(self) -> "EvaluationDraft":
        if not self.dimension_scores:
            raise ValueError("evaluation drafts require dimension_scores")
        return self


class EvaluatorOutput(AgentStructuredOutput):
    """Structured Evaluator output."""

    decisions: list[EvaluationDecision] = Field(default_factory=list)
    evaluation_drafts: list[EvaluationDraft] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_evaluator_output(self) -> "EvaluatorOutput":
        if not (self.evaluation_ids or self.decisions or self.evaluation_drafts):
            raise ValueError(
                "evaluator output requires evaluation_ids, decisions, or evaluation_drafts"
            )
        return self


class WatchlistDraft(ConnorBaseModel):
    """Watchlist Agent proposal for an active tracking item."""

    watchlist_id: str | None = None
    source_evaluation_id: str | None = None
    cluster_ids: list[str] = Field(default_factory=list)
    topic: NonEmptyStr
    thesis: NonEmptyStr
    watch_tier: WatchTier
    priority: PriorityLevel = PriorityLevel.MEDIUM
    ttl_days: int | None = None
    revisit_cadence_days: int = 1
    reactivation_rules: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    thread_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_watchlist_draft(self) -> "WatchlistDraft":
        if not self.reactivation_rules:
            raise ValueError("watchlist drafts require reactivation_rules")
        if self.revisit_cadence_days <= 0:
            raise ValueError("revisit_cadence_days must be positive")
        if self.ttl_days is not None and self.ttl_days <= 0:
            raise ValueError("ttl_days must be positive")
        if not (self.source_evaluation_id or self.cluster_ids or self.evidence_ids):
            raise ValueError(
                "watchlist drafts require source_evaluation_id, cluster_ids, or evidence_ids"
            )
        return self


class ArchiveDraft(ConnorBaseModel):
    """Watchlist Agent proposal for an inactive archived signal."""

    archive_id: str | None = None
    original_cluster_id: str | None = None
    original_watchlist_id: str | None = None
    thread_id: str | None = None
    archive_reason: ArchiveReason
    final_state: NonEmptyStr
    reactivation_hint: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_archive_draft(self) -> "ArchiveDraft":
        if not any([self.original_cluster_id, self.original_watchlist_id]):
            raise ValueError("archive drafts require original_cluster_id or original_watchlist_id")
        return self


class ThreadTimelineDraft(ConnorBaseModel):
    """Watchlist Agent proposal for one thread timeline entry."""

    event_at: AwareDatetime | None = None
    summary: NonEmptyStr
    confidence_at_time: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    later_outcome: LaterOutcome = LaterOutcome.PENDING
    cluster_id: str | None = None
    watchlist_id: str | None = None
    archive_id: str | None = None
    report_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_thread_timeline_draft(self) -> "ThreadTimelineDraft":
        if not any([self.cluster_id, self.watchlist_id, self.archive_id, self.report_id]):
            raise ValueError("thread timeline drafts require at least one linked object id")
        return self


class ThreadDraft(ConnorBaseModel):
    """Watchlist Agent proposal for a long-running intelligence thread."""

    thread_id: str | None = None
    title: NonEmptyStr
    status: ThreadStatus = ThreadStatus.ACTIVE
    importance: PriorityLevel = PriorityLevel.MEDIUM
    entities: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    current_thesis: NonEmptyStr
    timeline: list[ThreadTimelineDraft] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    linked_cluster_ids: list[str] = Field(default_factory=list)
    linked_watchlist_ids: list[str] = Field(default_factory=list)
    linked_archive_ids: list[str] = Field(default_factory=list)
    linked_report_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_thread_draft(self) -> "ThreadDraft":
        if not self.timeline:
            raise ValueError("thread drafts require at least one timeline entry")
        return self


class WatchlistAgentOutput(AgentStructuredOutput):
    """Structured Watchlist Agent output."""

    watchlist_drafts: list[WatchlistDraft] = Field(default_factory=list)
    archive_drafts: list[ArchiveDraft] = Field(default_factory=list)
    thread_drafts: list[ThreadDraft] = Field(default_factory=list)
    archive_ids: list[str] = Field(default_factory=list)
    thread_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_watchlist_output(self) -> "WatchlistAgentOutput":
        if not (
            self.watchlist_ids
            or self.archive_ids
            or self.thread_ids
            or self.watchlist_drafts
            or self.archive_drafts
            or self.thread_drafts
        ):
            raise ValueError(
                "watchlist output requires watchlist/archive/thread ids or drafts"
            )
        return self


class ReportItemDraft(ConnorBaseModel):
    """Writer/Editor proposal for one rendered report item."""

    item_id: str | None = None
    title: NonEmptyStr
    category: CandidateCategory
    status_label: NonEmptyStr
    core_information: NonEmptyStr
    why_it_matters: NonEmptyStr
    potential_impact: str | None = None
    key_data: list[str] = Field(default_factory=list)
    tickers: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    cluster_ids: list[str] = Field(default_factory=list)
    followup_points: list[str] = Field(default_factory=list)
    uncertainty_label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("evidence_ids", "cluster_ids", "tickers")
    @classmethod
    def values_must_be_unique(cls, value: list[str]) -> list[str]:
        return normalize_unique(value)

    @model_validator(mode="after")
    def validate_report_item_draft(self) -> "ReportItemDraft":
        if not self.evidence_ids:
            raise ValueError("report item drafts require evidence_ids")
        if not self.cluster_ids:
            raise ValueError("report item drafts require cluster_ids")
        if self.category == CandidateCategory.EARLY_SIGNAL and not self.uncertainty_label:
            raise ValueError("early-signal report item drafts require uncertainty_label")
        if self.category == CandidateCategory.TECH_FINANCE and not (
            self.tickers or self.potential_impact
        ):
            raise ValueError("tech-finance report item drafts require tickers or potential_impact")
        return self


class ReportSectionDraft(ConnorBaseModel):
    """Writer/Editor proposal for one report section."""

    section_id: NonEmptyStr
    title: NonEmptyStr
    items: list[ReportItemDraft] = Field(default_factory=list)


class ReportDraft(ConnorBaseModel):
    """Writer/Editor proposal for a DailyReport record."""

    report_id: str | None = None
    title: NonEmptyStr = "Connor.ai Daily Intelligence"
    full_markdown: str | None = None
    sections: list[ReportSectionDraft] = Field(default_factory=list)
    watchlist_updates: list[dict[str, Any]] = Field(default_factory=list)
    overview_judgments: list[str] = Field(default_factory=list)
    tomorrow_focus: list[str] = Field(default_factory=list)
    quality_score: Score | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_report_draft(self) -> "ReportDraft":
        if not self.sections:
            raise ValueError("report drafts require sections")
        if not any(section.items for section in self.sections):
            raise ValueError("report drafts require at least one section item")
        return self


class ReviewIssueDraft(ConnorBaseModel):
    """Reviewer proposal for an actionable review issue."""

    priority: int = Field(ge=0, le=3)
    title: NonEmptyStr
    body: NonEmptyStr
    report_item_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewDraft(ConnorBaseModel):
    """Reviewer proposal for a ReviewResult record."""

    review_result_id: str | None = None
    report_id: str | None = None
    decision: ReviewDecision
    issues: list[ReviewIssueDraft] = Field(default_factory=list)
    required_changes: list[str] = Field(default_factory=list)
    reasoning_summary: NonEmptyStr
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_review_draft(self) -> "ReviewDraft":
        if self.decision == ReviewDecision.PASS and (self.issues or self.required_changes):
            raise ValueError("pass review drafts cannot include issues or required_changes")
        if self.decision != ReviewDecision.PASS and not (self.issues or self.required_changes):
            raise ValueError("non-pass review drafts require issues or required_changes")
        return self


class WriterOutput(AgentStructuredOutput):
    """Structured Writer output."""

    markdown_preview: str | None = None
    report_drafts: list[ReportDraft] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_writer_output(self) -> "WriterOutput":
        if not (self.report_ids or self.report_drafts):
            raise ValueError("writer output requires report_ids or report_drafts")
        return self


class ReviewerOutput(AgentStructuredOutput):
    """Structured Reviewer output."""

    review_result_ids: list[str] = Field(default_factory=list)
    decision: ReviewDecision
    required_changes: list[str] = Field(default_factory=list)
    review_drafts: list[ReviewDraft] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_reviewer_output(self) -> "ReviewerOutput":
        draft_changes = [
            change
            for draft in self.review_drafts
            for change in [*draft.required_changes, *[issue.title for issue in draft.issues]]
        ]
        if not (self.review_result_ids or self.review_drafts):
            raise ValueError("reviewer output requires review_result_ids or review_drafts")
        if self.decision != ReviewDecision.PASS and not (self.required_changes or draft_changes):
            raise ValueError("non-pass reviewer output requires required_changes")
        return self


class EditorOutput(AgentStructuredOutput):
    """Structured Editor output."""

    edited_report_ids: list[str] = Field(default_factory=list)
    revised_report_drafts: list[ReportDraft] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_editor_output(self) -> "EditorOutput":
        if not (self.edited_report_ids or self.revised_report_drafts):
            raise ValueError("editor output requires edited_report_ids or revised_report_drafts")
        return self
