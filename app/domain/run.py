"""Run state schemas."""

from datetime import date
from typing import Any

from pydantic import Field, model_validator

from app.domain.base import ConnorBaseModel, DomainModel, NonEmptyStr
from app.domain.enums import RunPhase, RunStatus, SourceType


class RunLoopCounters(ConnorBaseModel):
    """Counters used by the loop harness to enforce boundaries."""

    collect_rounds: int = Field(default=0, ge=0)
    followup_rounds: int = Field(default=0, ge=0)
    writing_rounds: int = Field(default=0, ge=0)
    review_rounds: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0)


class RunBudgets(ConnorBaseModel):
    """Budget limits for a run."""

    max_collect_rounds: int = Field(default=3, gt=0)
    max_followup_rounds: int = Field(default=2, ge=0)
    max_writing_rounds: int = Field(default=3, gt=0)
    max_tool_calls: int = Field(default=100, gt=0)
    max_model_calls: int = Field(default=50, gt=0)
    max_runtime_seconds: int | None = Field(default=None, gt=0)


class RunState(DomainModel):
    """Top-level state for one Connor.ai daily run."""

    report_date: date
    objective: NonEmptyStr
    phase: RunPhase = RunPhase.INITIALIZE
    status: RunStatus = RunStatus.SCHEDULED
    loop_counters: RunLoopCounters = Field(default_factory=RunLoopCounters)
    budgets: RunBudgets = Field(default_factory=RunBudgets)
    enabled_sources: list[SourceType] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)
    cluster_ids: list[str] = Field(default_factory=list)
    selected_cluster_ids: list[str] = Field(default_factory=list)
    watchlist_ids: list[str] = Field(default_factory=list)
    archived_signal_ids: list[str] = Field(default_factory=list)
    thread_ids: list[str] = Field(default_factory=list)
    report_id: str | None = None
    metrics: dict[str, int | float] = Field(default_factory=dict)
    error_summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_run_state(self) -> "RunState":
        if self.status == RunStatus.COMPLETED and self.phase != RunPhase.FINALIZED:
            raise ValueError("completed runs must be in finalized phase")
        if self.status == RunStatus.FAILED and not self.error_summary:
            raise ValueError("failed runs require error_summary")
        if self.loop_counters.collect_rounds > self.budgets.max_collect_rounds:
            raise ValueError("collect_rounds exceeds max_collect_rounds")
        if self.loop_counters.followup_rounds > self.budgets.max_followup_rounds:
            raise ValueError("followup_rounds exceeds max_followup_rounds")
        if self.loop_counters.writing_rounds > self.budgets.max_writing_rounds:
            raise ValueError("writing_rounds exceeds max_writing_rounds")
        return self

