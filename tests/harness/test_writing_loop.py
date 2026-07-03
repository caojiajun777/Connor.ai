"""Writing loop harness tests."""

from app.domain import RunPhase
from app.harness import HarnessConfig, HarnessContext, WritingGateOutcome, WritingLoopHarness
from app.repositories import DailyReportRepository, RunRepository
from tests.domain.fixtures import RUN_ID, run_state_fixture
from tests.harness.helpers import ScriptedWritingAgentRunner, writing_tasks


def test_writing_loop_revises_then_finalizes(db_session) -> None:
    run = run_state_fixture().model_copy(
        update={
            "phase": RunPhase.WRITING,
            "selected_cluster_ids": ["cl_openai_reasoning_api"],
        }
    )
    RunRepository(db_session).add(run)
    agent_runner = ScriptedWritingAgentRunner(db_session)
    context = HarnessContext(
        db_session,
        agent_runner=agent_runner,
        config=HarnessConfig(max_writing_revisions=2),
    )

    next_run, decisions = WritingLoopHarness(context).run(run, tasks_by_phase=writing_tasks())

    assert next_run.status == "completed"
    assert next_run.phase == "finalized"
    assert next_run.report_id == "report_harness"
    assert [decision.outcome for decision in decisions] == [
        WritingGateOutcome.REVISE,
        WritingGateOutcome.FINALIZE,
    ]
    assert DailyReportRepository(db_session).require("report_harness").status == "final"
    assert [call.agent_role for call in agent_runner.calls] == [
        "writer",
        "reviewer",
        "editor",
        "reviewer",
    ]
