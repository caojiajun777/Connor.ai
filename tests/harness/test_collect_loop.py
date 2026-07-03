"""Collect loop harness tests."""

from app.domain import RunBudgets
from app.harness import CollectGateOutcome, CollectLoopHarness, HarnessConfig, HarnessContext
from app.repositories import ArtifactRepository, RunRepository
from app.services import TraceService
from tests.domain.fixtures import RUN_ID, early_signal_bundle, run_state_fixture
from tests.harness.helpers import persist_bundle


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
