"""Agent role registry tests."""

from app.agents import (
    EvaluatorOutput,
    ScoutOutput,
    WriterOutput,
    create_default_agent_role_registry,
)
from app.domain import AgentRole
from app.tools import create_default_tool_registry


def test_default_agent_role_registry_binds_output_models_and_tools() -> None:
    tool_registry = create_default_tool_registry()
    agent_registry = create_default_agent_role_registry(tool_registry)

    social_config = agent_registry.require(AgentRole.SOCIAL_SCOUT)
    frontier_config = agent_registry.require(AgentRole.FRONTIER_EVALUATOR)
    writer_config = agent_registry.require(AgentRole.WRITER)

    assert social_config.output_model is ScoutOutput
    assert frontier_config.output_model is EvaluatorOutput
    assert writer_config.output_model is WriterOutput
    assert "manual_seed" in social_config.allowed_tool_names
    assert "mock_search" in frontier_config.allowed_tool_names
    assert "manual_seed" not in writer_config.allowed_tool_names

