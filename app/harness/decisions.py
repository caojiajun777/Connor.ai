"""Decision and task schemas for the Connor loop harness."""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from app.domain import AgentRole, RunPhase, RunState
from app.domain.base import ConnorBaseModel, NonEmptyStr
from app.domain.enums import StrEnum


class CollectGateOutcome(StrEnum):
    """Programmatic outcomes from the collect quality gate."""

    ENTER_WRITING = "enter_writing"
    FOLLOWUP_NOW = "followup_now"
    RECLUSTER = "recluster"
    CONTINUE_COLLECTING = "continue_collecting"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"
    FAIL = "fail"


class WritingGateOutcome(StrEnum):
    """Programmatic outcomes from the writing quality gate."""

    FINALIZE = "finalize"
    REVIEW_DRAFT = "review_draft"
    REVISE = "revise"
    REOPEN_COLLECT = "reopen_collect"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"
    FAIL = "fail"


class AgentTask(ConnorBaseModel):
    """One role assignment issued by the harness to AgentScope AgentRunner."""

    agent_role: AgentRole
    phase: RunPhase
    task: NonEmptyStr
    context: dict[str, Any] = Field(default_factory=dict)
    required: bool = True


class CollectGateDecision(ConnorBaseModel):
    """Collect loop quality-gate decision."""

    outcome: CollectGateOutcome
    reasoning_summary: NonEmptyStr
    selected_cluster_ids: list[str] = Field(default_factory=list)
    followup_queries: list[str] = Field(default_factory=list)
    recluster_cluster_ids: list[str] = Field(default_factory=list)
    watchlist_ids: list[str] = Field(default_factory=list)
    archive_ids: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    metrics: dict[str, int | float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_outcome_requirements(self) -> "CollectGateDecision":
        if self.outcome == CollectGateOutcome.ENTER_WRITING and not self.selected_cluster_ids:
            raise ValueError("enter_writing requires selected_cluster_ids")
        if self.outcome == CollectGateOutcome.FOLLOWUP_NOW and not self.followup_queries:
            raise ValueError("followup_now requires followup_queries")
        if self.outcome == CollectGateOutcome.RECLUSTER and not (
            self.recluster_cluster_ids or self.risk_flags
        ):
            raise ValueError("recluster requires recluster_cluster_ids or risk_flags")
        if self.outcome == CollectGateOutcome.FAIL and not self.risk_flags:
            raise ValueError("fail requires risk_flags")
        return self


class WritingGateDecision(ConnorBaseModel):
    """Writing loop quality-gate decision."""

    outcome: WritingGateOutcome
    reasoning_summary: NonEmptyStr
    report_id: str | None = None
    review_result_id: str | None = None
    required_changes: list[str] = Field(default_factory=list)
    reopen_collect_reasons: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    metrics: dict[str, int | float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_outcome_requirements(self) -> "WritingGateDecision":
        if self.outcome == WritingGateOutcome.FINALIZE and not self.report_id:
            raise ValueError("finalize requires report_id")
        if self.outcome == WritingGateOutcome.REVISE and not self.required_changes:
            raise ValueError("revise requires required_changes")
        if self.outcome == WritingGateOutcome.REOPEN_COLLECT and not self.reopen_collect_reasons:
            raise ValueError("reopen_collect requires reopen_collect_reasons")
        if self.outcome == WritingGateOutcome.FAIL and not self.risk_flags:
            raise ValueError("fail requires risk_flags")
        return self


class DailyRunResult(ConnorBaseModel):
    """Final result returned by DailyRunHarness."""

    run: RunState
    collect_decisions: list[CollectGateDecision] = Field(default_factory=list)
    writing_decisions: list[WritingGateDecision] = Field(default_factory=list)
    final_report_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
