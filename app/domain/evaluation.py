"""Evaluation result schemas."""

from typing import Any

from pydantic import Field, field_validator, model_validator

from app.domain.base import DomainModel, NonEmptyStr, Score
from app.domain.enums import AgentRole, EvaluationDecision, EvaluationType, WritePolicy


class EvaluationResult(DomainModel):
    """A structured evaluator decision for a cluster."""

    run_id: NonEmptyStr
    cluster_id: NonEmptyStr
    evaluator_type: EvaluationType
    created_by_agent: AgentRole
    dimension_scores: dict[str, Score] = Field(default_factory=dict)
    total_score: Score
    decision: EvaluationDecision
    reasoning_summary: NonEmptyStr
    risk_flags: list[str] = Field(default_factory=list)
    required_followups: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    write_policy: WritePolicy | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("dimension_scores")
    @classmethod
    def require_named_scores(cls, value: dict[str, float]) -> dict[str, float]:
        if not value:
            raise ValueError("evaluation requires dimension_scores")
        return value

    @model_validator(mode="after")
    def validate_decision_requirements(self) -> "EvaluationResult":
        if self.decision == EvaluationDecision.SELECT_EARLY_SIGNAL:
            if self.evaluator_type != EvaluationType.FRONTIER:
                raise ValueError("select_early_signal decisions must come from frontier evaluation")
            if not self.required_followups:
                raise ValueError("select_early_signal requires required_followups")

        if self.decision == EvaluationDecision.SELECT_CONFIRMED:
            if self.missing_evidence:
                raise ValueError("select_confirmed cannot have missing_evidence")
            if self.total_score < 6:
                raise ValueError("select_confirmed requires total_score >= 6")

        if self.decision in {
            EvaluationDecision.FOLLOWUP_NOW,
            EvaluationDecision.FOLLOWUP_LATER,
        } and not self.required_followups:
            raise ValueError("follow-up decisions require required_followups")

        if self.decision == EvaluationDecision.RECLUSTER and not self.risk_flags:
            raise ValueError("recluster decisions require risk_flags explaining the issue")

        return self

