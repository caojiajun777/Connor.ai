"""Tool contracts for Connor.ai."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.domain import (
    AgentRole,
    EvidenceItem,
    EvidenceStrength,
    SourceAccessLevel,
    SourceType,
    ToolCallRecord,
    ToolEnvelope,
    TraceEvent,
)
from app.domain.enums import RunPhase


class ToolExecutionError(RuntimeError):
    """Raised when tool registration or execution violates the Connor.ai contract."""


@dataclass(frozen=True)
class ToolExecutionContext:
    """Context passed to a registered tool implementation."""

    run_id: str
    phase: RunPhase
    agent_role: AgentRole
    query: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolSpec:
    """Static metadata and policy for a tool."""

    name: str
    description: str
    source_type: SourceType
    allowed_agent_roles: frozenset[AgentRole]
    default_source_name: str | None = None
    default_access_level: SourceAccessLevel = SourceAccessLevel.PUBLIC
    default_evidence_strength: EvidenceStrength = EvidenceStrength.UNKNOWN
    timeout_seconds: int | None = None
    stores_raw_payload: bool = True

    def allows(self, agent_role: AgentRole) -> bool:
        return agent_role in self.allowed_agent_roles


ToolFunction = Callable[[ToolExecutionContext], ToolEnvelope | dict[str, Any]]


@dataclass(frozen=True)
class RegisteredTool:
    """A callable tool and its Connor.ai contract."""

    spec: ToolSpec
    func: ToolFunction


@dataclass(frozen=True)
class ToolExecutionResult:
    """Result returned by ToolExecutor."""

    spec: ToolSpec
    envelope: ToolEnvelope
    evidence_items: list[EvidenceItem]
    tool_call: ToolCallRecord
    trace_event: TraceEvent
    evidence_trace_event: TraceEvent | None = None

