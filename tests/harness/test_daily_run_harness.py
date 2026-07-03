"""Top-level DailyRunHarness tests."""

from app.domain import RunBudgets, RunPhase
from app.harness import DailyRunHarness, HarnessConfig
from app.repositories import RunRepository
from app.services import TraceService
from tests.domain.fixtures import RUN_ID, early_signal_bundle, run_state_fixture
from tests.harness.helpers import ScriptedWritingAgentRunner, persist_bundle, writing_tasks


def test_daily_run_harness_collects_then_writes_final_report(db_session) -> None:
    agent_runner = ScriptedWritingAgentRunner(db_session)
    harness = DailyRunHarness(
        db_session,
        agent_runner=agent_runner,
        config=HarnessConfig(min_selected_items=1, max_writing_revisions=2),
    )
    run = harness.create_run(
        run_id=RUN_ID,
        report_date=run_state_fixture().report_date,
        objective=run_state_fixture().objective,
        budgets=RunBudgets(max_collect_rounds=2, max_writing_rounds=3),
    )
    persist_bundle(db_session, early_signal_bundle())

    result = harness.run(run, writing_tasks_by_phase=writing_tasks())

    assert result.run.status == "completed"
    assert result.run.phase == RunPhase.FINALIZED
    assert result.final_report_id == "report_harness"
    assert result.collect_decisions[-1].outcome == "enter_writing"
    assert result.writing_decisions[-1].outcome == "finalize"

    persisted = RunRepository(db_session).require(RUN_ID)
    assert persisted.report_id == "report_harness"

    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)
    event_types = [event.event_type for event in timeline.events]
    assert "run_started" in event_types
    assert "report_finalized" in event_types
