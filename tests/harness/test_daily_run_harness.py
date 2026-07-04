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


def test_daily_run_harness_reraises_unexpected_exceptions_and_records_traceback(db_session) -> None:
    import pytest

    from app.domain import TraceEventType

    harness = DailyRunHarness(db_session, config=HarnessConfig(min_selected_items=1))
    run = harness.create_run(
        run_id=RUN_ID,
        report_date=run_state_fixture().report_date,
        objective=run_state_fixture().objective,
        budgets=RunBudgets(max_collect_rounds=2),
    )

    def explode(*args, **kwargs):
        raise AttributeError("boom")

    harness.collect_loop.run = explode

    with pytest.raises(AttributeError, match="boom"):
        harness.run(run)

    failed = RunRepository(db_session).require(RUN_ID)
    assert failed.status == "failed"
    assert failed.error_summary == "boom"

    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)
    error_events = [event for event in timeline.events if event.event_type == TraceEventType.ERROR]
    assert error_events
    assert "Traceback" in error_events[-1].error
    assert "AttributeError: boom" in error_events[-1].error


def test_daily_run_harness_refuses_to_resume_failed_run(db_session) -> None:
    import pytest

    from app.domain import RunStatus
    from app.harness import HarnessError

    failed_run = run_state_fixture().model_copy(
        update={"status": RunStatus.FAILED, "error_summary": "previous failure"}
    )
    RunRepository(db_session).add(failed_run)
    db_session.flush()
    harness = DailyRunHarness(db_session, config=HarnessConfig(min_selected_items=1))

    with pytest.raises(HarnessError, match="failed runs cannot be resumed directly"):
        harness.resume(RUN_ID)
