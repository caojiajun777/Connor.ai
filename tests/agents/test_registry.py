"""Agent role registry tests."""

import asyncio

from app.agents import (
    AgentScopeToolBridge,
    ClustererOutput,
    EvaluatorOutput,
    ScoutOutput,
    WatchlistAgentOutput,
    WriterOutput,
    create_default_agent_role_registry,
)
from app.domain import AgentRole, RunPhase
from app.tools import ToolExecutor, create_default_tool_registry
from tests.domain.fixtures import RUN_ID


def test_default_agent_role_registry_binds_output_models_and_tools() -> None:
    tool_registry = create_default_tool_registry()
    agent_registry = create_default_agent_role_registry(tool_registry)

    social_config = agent_registry.require(AgentRole.SOCIAL_SCOUT)
    clusterer_config = agent_registry.require(AgentRole.CLUSTERER)
    frontier_config = agent_registry.require(AgentRole.FRONTIER_EVALUATOR)
    watchlist_config = agent_registry.require(AgentRole.WATCHLIST_AGENT)
    writer_config = agent_registry.require(AgentRole.WRITER)

    assert social_config.output_model is ScoutOutput
    assert clusterer_config.output_model is ClustererOutput
    assert frontier_config.output_model is EvaluatorOutput
    assert watchlist_config.output_model is WatchlistAgentOutput
    assert writer_config.output_model is WriterOutput
    assert "Evaluator profile:" in frontier_config.system_prompt
    assert "information_gap" in frontier_config.system_prompt
    assert "Watchlist memory profile:" in watchlist_config.system_prompt
    assert "archive_drafts" in watchlist_config.system_prompt
    assert "manual_seed" in social_config.allowed_tool_names
    assert "mock_search" in frontier_config.allowed_tool_names
    assert "manual_seed" not in writer_config.allowed_tool_names


def test_agentscope_bridge_marks_connor_tools_sequential(db_session) -> None:
    tool_registry = create_default_tool_registry()
    bridge = AgentScopeToolBridge(
        tool_registry=tool_registry,
        tool_executor=ToolExecutor(db_session, registry=tool_registry),
        run_id=RUN_ID,
        phase=RunPhase.SCOUTING,
        agent_role=AgentRole.SOCIAL_SCOUT,
    )

    toolkit = bridge.create_toolkit(["manual_seed"])
    tool = asyncio.run(toolkit.get_tool("manual_seed"))

    assert tool is not None
    assert tool.is_concurrency_safe is False
