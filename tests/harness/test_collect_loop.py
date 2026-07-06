"""Collect loop harness tests."""

import pytest

from app.agents import AgentRunRequest, AgentScopeExecutionError
from app.domain import AgentRole, RunBudgets, RunPhase
from app.harness import (
    AgentTask,
    CollectGateOutcome,
    CollectLoopHarness,
    HarnessConfig,
    HarnessContext,
)
from app.repositories import ArtifactRepository, RunRepository, WatchlistRepository
from app.services import TraceService
from tests.domain.fixtures import RUN_ID, early_signal_bundle, run_state_fixture
from tests.harness.helpers import persist_bundle


class FailingScoutAgentRunner:
    def __init__(self):
        self.calls: list[AgentRunRequest] = []

    def run(self, request: AgentRunRequest):
        self.calls.append(request)
        raise AgentScopeExecutionError("scout model timed out")


def test_collect_loop_enters_writing_with_selected_evaluation(db_session) -> None:
    run = run_state_fixture().model_copy(update={"budgets": RunBudgets(max_collect_rounds=2)})
    RunRepository(db_session).add(run)
    persist_bundle(db_session, early_signal_bundle())

    context = HarnessContext(db_session, config=HarnessConfig(min_selected_items=1))
    next_run, decisions = CollectLoopHarness(context).run(run)

    assert next_run.phase == "writing"
    assert decisions[-1].outcome == CollectGateOutcome.ENTER_WRITING
    assert decisions[-1].selected_cluster_ids == ["cl_openai_reasoning_api"]
    assert RunRepository(db_session).require(RUN_ID).selected_cluster_ids == [
        "cl_openai_reasoning_api"
    ]

    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)
    assert any(event.event_type == "gate_decision" for event in timeline.events)
    assert ArtifactRepository(db_session).list_by_run(RUN_ID)


def test_collect_loop_pauses_when_budget_exhausted(db_session) -> None:
    run = run_state_fixture().model_copy(update={"budgets": RunBudgets(max_collect_rounds=1)})
    RunRepository(db_session).add(run)

    context = HarnessContext(db_session, config=HarnessConfig(min_selected_items=1))
    next_run, decisions = CollectLoopHarness(context).run(run)

    assert next_run.status == "paused"
    assert decisions[-1].outcome == CollectGateOutcome.NEEDS_MANUAL_REVIEW
    assert next_run.metadata["manual_review_required"] is True


def test_collect_loop_continues_when_scout_agent_execution_fails(db_session) -> None:
    run = run_state_fixture().model_copy(update={"budgets": RunBudgets(max_collect_rounds=1)})
    RunRepository(db_session).add(run)
    agent_runner = FailingScoutAgentRunner()
    context = HarnessContext(
        db_session,
        agent_runner=agent_runner,
        config=HarnessConfig(min_selected_items=1),
    )

    next_run, decisions = CollectLoopHarness(context).run(
        run,
        tasks_by_phase={
            RunPhase.SCOUTING: [
                AgentTask(
                    agent_role=AgentRole.SOCIAL_SCOUT,
                    phase=RunPhase.SCOUTING,
                    task="Scout with a forced runtime failure.",
                )
            ],
        },
    )

    assert len(agent_runner.calls) == 1
    assert next_run.status == "paused"
    assert decisions[-1].outcome == CollectGateOutcome.NEEDS_MANUAL_REVIEW
    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)
    assert any(
        event.summary == "Harness dispatching social_scout task."
        and event.metadata["task_progress"] is True
        and event.metadata["task_index"] == 1
        for event in timeline.events
    )
    assert any(
        event.summary == "Scout task failed; continuing collect."
        and event.status == "failed"
        and event.metadata["skipped_task"] is True
        for event in timeline.events
    )


def test_collect_loop_continues_when_watchlist_agent_execution_fails(db_session) -> None:
    run = run_state_fixture().model_copy(update={"budgets": RunBudgets(max_collect_rounds=1)})
    RunRepository(db_session).add(run)
    persist_bundle(db_session, early_signal_bundle())
    agent_runner = FailingScoutAgentRunner()
    context = HarnessContext(
        db_session,
        agent_runner=agent_runner,
        config=HarnessConfig(min_selected_items=1),
    )

    next_run, decisions = CollectLoopHarness(context).run(
        run,
        tasks_by_phase={
            RunPhase.WATCHLIST_UPDATE: [
                AgentTask(
                    agent_role=AgentRole.WATCHLIST_AGENT,
                    phase=RunPhase.WATCHLIST_UPDATE,
                    task="Update watchlist with a forced runtime failure.",
                )
            ],
        },
    )

    assert len(agent_runner.calls) == 1
    assert next_run.phase == "writing"
    assert decisions[-1].outcome == CollectGateOutcome.ENTER_WRITING
    assert WatchlistRepository(db_session).list_by_run(RUN_ID)
    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)
    assert any(
        event.summary == "Watchlist task failed; continuing collect."
        and event.status == "failed"
        and event.metadata["continue_on_watchlist_agent_error"] is True
        for event in timeline.events
    )


def test_collect_loop_can_fail_fast_on_scout_agent_execution_error(db_session) -> None:
    run = run_state_fixture().model_copy(update={"budgets": RunBudgets(max_collect_rounds=1)})
    RunRepository(db_session).add(run)
    context = HarnessContext(
        db_session,
        agent_runner=FailingScoutAgentRunner(),
        config=HarnessConfig(min_selected_items=1, continue_on_scout_agent_error=False),
    )

    with pytest.raises(AgentScopeExecutionError, match="scout model timed out"):
        CollectLoopHarness(context).run(
            run,
            tasks_by_phase={
                RunPhase.SCOUTING: [
                    AgentTask(
                        agent_role=AgentRole.SOCIAL_SCOUT,
                        phase=RunPhase.SCOUTING,
                        task="Scout with a forced runtime failure.",
                    )
                ],
            },
        )
