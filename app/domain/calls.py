"""Tool and model call records."""

from typing import Any

from pydantic import Field, model_validator

from app.domain.base import ArtifactRef, AwareDatetime, DomainModel, NonEmptyStr, utc_now
from app.domain.enums import AgentRole, ModelCallStatus, SourceType, ToolCallStatus


class ToolCallRecord(DomainModel):
    """Persistable summary of a tool call."""

    run_id: NonEmptyStr
    agent_role: AgentRole
    tool_name: NonEmptyStr
    source_type: SourceType | None = None
    query: str | None = None
    status: ToolCallStatus = ToolCallStatus.QUEUED
    started_at: AwareDatetime = Field(default_factory=utc_now)
    ended_at: AwareDatetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    trace_event_id: str | None = None
    request_artifact_ref: ArtifactRef | None = None
    response_artifact_ref: ArtifactRef | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_tool_call_status(self) -> "ToolCallRecord":
        if self.ended_at and self.ended_at < self.started_at:
            raise ValueError("ended_at cannot be earlier than started_at")
        if self.status in {
            ToolCallStatus.FAILED,
            ToolCallStatus.TIMEOUT,
            ToolCallStatus.RATE_LIMITED,
        } and not self.error:
            raise ValueError("failed, timeout, or rate-limited tool calls require error")
        return self


class ModelCallRecord(DomainModel):
    """Persistable summary of an LLM/model call."""

    run_id: NonEmptyStr
    agent_role: AgentRole
    model_provider: NonEmptyStr
    model_name: NonEmptyStr
    status: ModelCallStatus = ModelCallStatus.QUEUED
    started_at: AwareDatetime = Field(default_factory=utc_now)
    ended_at: AwareDatetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    trace_event_id: str | None = None
    prompt_artifact_ref: ArtifactRef | None = None
    response_artifact_ref: ArtifactRef | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_model_call_status(self) -> "ModelCallRecord":
        if self.ended_at and self.ended_at < self.started_at:
            raise ValueError("ended_at cannot be earlier than started_at")
        if self.status in {ModelCallStatus.FAILED, ModelCallStatus.TIMEOUT} and not self.error:
            raise ValueError("failed or timeout model calls require error")
        return self

