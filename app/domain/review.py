"""Review schemas for the writing loop."""

from typing import Any

from pydantic import Field, model_validator

from app.domain.base import DomainModel, NonEmptyStr
from app.domain.enums import AgentRole, ReviewDecision


class ReviewIssue(DomainModel):
    """An actionable report review issue."""

    run_id: NonEmptyStr
    report_id: NonEmptyStr
    priority: int = Field(ge=0, le=3)
    title: NonEmptyStr
    body: NonEmptyStr
    report_item_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewResult(DomainModel):
    """A structured Reviewer decision over a draft report."""

    run_id: NonEmptyStr
    report_id: NonEmptyStr
    reviewer_agent: AgentRole = AgentRole.REVIEWER
    decision: ReviewDecision
    issues: list[ReviewIssue] = Field(default_factory=list)
    required_changes: list[str] = Field(default_factory=list)
    reasoning_summary: NonEmptyStr
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_review_decision(self) -> "ReviewResult":
        if self.decision == ReviewDecision.PASS and (self.issues or self.required_changes):
            raise ValueError("pass reviews cannot include issues or required_changes")
        if self.decision != ReviewDecision.PASS and not (self.issues or self.required_changes):
            raise ValueError("non-pass reviews require issues or required_changes")
        return self

