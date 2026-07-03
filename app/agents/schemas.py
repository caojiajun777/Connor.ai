"""AgentScope runner request and result schemas."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.agents.outputs import AgentStructuredOutput
from app.domain import AgentRole, RunPhase, TraceEvent
from app.domain.base import ConnorBaseModel, NonEmptyStr
from app.tools import ToolExecutionResult


class AgentScopeExecutionError(RuntimeError):
    """Raised when AgentScope execution cannot produce a valid Connor result."""


class AgentRunRequest(ConnorBaseModel):
    """Request passed from the Connor harness into one AgentScope agent run."""

    run_id: NonEmptyStr
    phase: RunPhase
    agent_role: AgentRole
    task: NonEmptyStr
    context: dict[str, Any] = Field(default_factory=dict)


class AgentRunResult(ConnorBaseModel):
    """Connor-visible result of one AgentScope agent run."""

    run_id: NonEmptyStr
    phase: RunPhase
    agent_role: AgentRole
    output_text: str | None = None
    structured_output: AgentStructuredOutput
    tool_results: list[ToolExecutionResult] = Field(default_factory=list)
    start_trace_event: TraceEvent | None = None
    completion_trace_event: TraceEvent | None = None
    error_trace_event: TraceEvent | None = None

    model_config = {"arbitrary_types_allowed": True}
