"""Agent role registry tests."""

import asyncio
import time
from types import SimpleNamespace

from app.agents import (
    AgentScopeToolBridge,
    ClustererOutput,
    EvaluatorOutput,
    ScoutOutput,
    WatchlistAgentOutput,
    WriterOutput,
    create_default_agent_role_registry,
)
from app.domain import AgentRole, RunPhase, SourceType, ToolCallStatus
from app.tools import ToolExecutor, ToolSpec, create_default_tool_registry
from app.tools.registry import ToolRegistry
from tests.domain.fixtures import RUN_ID


def test_default_agent_role_registry_binds_output_models_and_tools() -> None:
    tool_registry = create_default_tool_registry()
    agent_registry = create_default_agent_role_registry(tool_registry, agent_timeout_seconds=120)

    social_config = agent_registry.require(AgentRole.SOCIAL_SCOUT)
    finance_config = agent_registry.require(AgentRole.FINANCE_SCOUT)
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
    assert social_config.execution.timeout_seconds == 120
    assert writer_config.execution.timeout_seconds == 120
    assert social_config.execution.max_iters == 4
    assert social_config.execution.max_tool_calls == 1
    assert finance_config.execution.max_iters == 4
    assert finance_config.execution.max_tool_calls == 2
    assert clusterer_config.execution.max_iters == 1
    assert clusterer_config.execution.max_tool_calls == 0
    assert writer_config.execution.max_iters == 1
    assert writer_config.execution.max_tool_calls == 0


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


def test_agentscope_bridge_offloads_sync_tool_execution_from_event_loop() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="slow_tool",
            description="Slow fake tool.",
            source_type=SourceType.MANUAL,
            allowed_agent_roles=frozenset({AgentRole.SOCIAL_SCOUT}),
        ),
        lambda _context: {},
    )
    bridge = AgentScopeToolBridge(
        tool_registry=registry,
        tool_executor=_SlowFakeToolExecutor(),
        run_id=RUN_ID,
        phase=RunPhase.SCOUTING,
        agent_role=AgentRole.SOCIAL_SCOUT,
    )

    async def run_tool_and_tick() -> None:
        toolkit = bridge.create_toolkit(["slow_tool"])
        tool = await toolkit.get_tool("slow_tool")
        assert tool is not None

        started = time.perf_counter()
        task = asyncio.create_task(tool(query="slow query"))
        await asyncio.sleep(0.03)
        elapsed_while_tool_runs = time.perf_counter() - started
        chunk = await task

        assert elapsed_while_tool_runs < 0.10
        assert bridge.executed_result_count() == 1
        assert chunk.state.value == "success"

    try:
        asyncio.run(run_tool_and_tick())
    finally:
        asyncio.run(bridge.aclose())


class _SlowFakeToolExecutor:
    def execute(self, **_kwargs):
        time.sleep(0.15)
        return SimpleNamespace(
            spec=SimpleNamespace(name="slow_tool"),
            envelope=SimpleNamespace(
                query="slow query",
                errors=[],
                raw_artifact_ref=None,
                metadata={},
            ),
            evidence_items=[],
            tool_call=SimpleNamespace(
                id="tool_slow",
                status=ToolCallStatus.SUCCEEDED,
            ),
            trace_event=SimpleNamespace(id="trace_slow"),
        )
