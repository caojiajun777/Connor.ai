"""Tool registry tests."""

import pytest

from app.domain import AgentRole, SourceType, ToolEnvelope
from app.tools import ToolExecutionContext, ToolExecutionError, ToolRegistry, ToolSpec


def noop_tool(context: ToolExecutionContext) -> ToolEnvelope:
    return ToolEnvelope(tool_name="noop", source_type=SourceType.OTHER, query=context.query)


def test_registry_registers_and_filters_by_agent_role() -> None:
    registry = ToolRegistry()
    spec = ToolSpec(
        name="noop",
        description="No-op tool",
        source_type=SourceType.OTHER,
        allowed_agent_roles=frozenset({AgentRole.SOCIAL_SCOUT}),
    )

    registry.register(spec, noop_tool)

    assert registry.require("noop").spec == spec
    assert registry.list_for_agent(AgentRole.SOCIAL_SCOUT) == [spec]
    assert registry.list_for_agent(AgentRole.FINANCE_SCOUT) == []


def test_registry_rejects_duplicate_tools() -> None:
    registry = ToolRegistry()
    spec = ToolSpec(
        name="noop",
        description="No-op tool",
        source_type=SourceType.OTHER,
        allowed_agent_roles=frozenset({AgentRole.SOCIAL_SCOUT}),
    )
    registry.register(spec, noop_tool)

    with pytest.raises(ToolExecutionError):
        registry.register(spec, noop_tool)


def test_registry_enforces_agent_role_permissions() -> None:
    registry = ToolRegistry()
    spec = ToolSpec(
        name="noop",
        description="No-op tool",
        source_type=SourceType.OTHER,
        allowed_agent_roles=frozenset({AgentRole.SOCIAL_SCOUT}),
    )
    registry.register(spec, noop_tool)

    with pytest.raises(ToolExecutionError):
        registry.require_allowed("noop", AgentRole.FINANCE_SCOUT)

