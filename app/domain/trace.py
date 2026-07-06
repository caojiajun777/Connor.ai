"""Trace event schemas."""

from typing import Any

from pydantic import Field, model_validator

from app.domain.base import ArtifactRef, DomainModel, FORBIDDEN_REASONING_KEYS, NonEmptyStr, ObjectRef
from app.domain.enums import AgentRole, RunPhase, TraceEventType, TraceStatus


class TraceEvent(DomainModel):
    """A replayable execution event that stores summaries, not hidden reasoning."""

    run_id: NonEmptyStr
    parent_id: str | None = None
    seq: int = Field(ge=0)
    phase: RunPhase
    agent_role: AgentRole | None = None
    event_type: TraceEventType
    status: TraceStatus = TraceStatus.SUCCEEDED
    summary: NonEmptyStr
    reasoning_summary: str | None = None
    tool_call_id: str | None = None
    model_call_id: str | None = None
    input_artifact_ref: ArtifactRef | None = None
    output_artifact_ref: ArtifactRef | None = None
    created_object_refs: list[ObjectRef] = Field(default_factory=list)
    duration_ms: int | None = Field(default=None, ge=0)
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_trace_boundaries(self) -> "TraceEvent":
        if self.reasoning_summary is not None:
            lower = self.reasoning_summary.lower()
            for key in FORBIDDEN_REASONING_KEYS:
                if key in lower:
                    raise ValueError(
                        f"reasoning_summary contains forbidden key reference: {key}"
                    )
        if self.status == TraceStatus.FAILED and not self.error:
            raise ValueError("failed trace events require error")
        return self

