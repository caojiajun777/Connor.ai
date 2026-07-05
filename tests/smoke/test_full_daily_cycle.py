"""Full daily intelligence cycle smoke test.

This test runs the complete Connor.ai pipeline with the real DeepSeek API.
It is skipped unless CONNOR_DEEPSEEK_API_KEY is configured.

Run with:
    python -m pytest tests/smoke/test_full_daily_cycle.py -v -s
"""

from datetime import date

import pytest

from app.agents import AgentRunner, create_deepseek_model_factory, create_default_agent_role_registry
from app.clusterer.tasks import ClusterTaskFactory
from app.config import get_settings
from app.db.session import SessionLocal
from app.domain import AgentRole, RunBudgets, RunPhase
from app.evaluators.tasks import EvaluatorTaskFactory
from app.harness import DailyRunHarness, HarnessConfig
from app.harness.decisions import AgentTask
from app.repositories import DailyReportRepository
from app.scouts.tasks import ScoutTaskFactory
from app.tools import create_default_tool_registry
from app.watchlist.tasks import WatchlistTaskFactory

_has_api_key = bool(get_settings().deepseek_api_key)

pytestmark = pytest.mark.skipif(
    not _has_api_key,
    reason="CONNOR_DEEPSEEK_API_KEY not set",
)


def build_collect_tasks(objective: str) -> dict[RunPhase, list[AgentTask]]:
    scout_factory = ScoutTaskFactory()
    cluster_factory = ClusterTaskFactory()
    evaluator_factory = EvaluatorTaskFactory()
    watchlist_factory = WatchlistTaskFactory()
    return {
        RunPhase.SCOUTING: scout_factory.create_all_tasks(objective=objective),
        RunPhase.CLUSTERING: [cluster_factory.create_task(objective=objective)],
        RunPhase.EVALUATING: evaluator_factory.create_all_tasks(objective=objective),
        RunPhase.WATCHLIST_UPDATE: [watchlist_factory.create_task(objective=objective)],
    }


def build_writing_tasks(objective: str) -> dict[RunPhase, list[AgentTask]]:
    return {
        RunPhase.WRITING: [
            AgentTask(
                agent_role=AgentRole.WRITER,
                phase=RunPhase.WRITING,
                task=(
                    "Write a structured daily intelligence report from selected clusters, "
                    "evaluations, evidence, watchlist, and thread context. "
                    "Produce report_drafts with sections and evidence_map coverage. "
                    "Early Signals must stay explicitly uncertain. "
                    f"Objective: {objective}"
                ),
            )
        ],
        RunPhase.REVIEWING: [
            AgentTask(
                agent_role=AgentRole.REVIEWER,
                phase=RunPhase.REVIEWING,
                task=(
                    "Review the draft report. Check early-signal language, evidence "
                    "coverage, and section consistency. Return review_drafts with a decision. "
                    f"Objective: {objective}"
                ),
            )
        ],
        RunPhase.EDITING: [
            AgentTask(
                agent_role=AgentRole.EDITOR,
                phase=RunPhase.EDITING,
                task=(
                    "Revise the draft based on review issues. Return revised_report_drafts. "
                    f"Objective: {objective}"
                ),
            )
        ],
        RunPhase.FINAL_REVIEW: [
            AgentTask(
                agent_role=AgentRole.REVIEWER,
                phase=RunPhase.FINAL_REVIEW,
                task=(
                    "Final review of the revised report. Return review_drafts with PASS "
                    "if ready to finalize. "
                    f"Objective: {objective}"
                ),
            )
        ],
    }


@pytest.mark.slow
def test_full_daily_cycle():
    """Full Connor.ai daily intelligence cycle with real DeepSeek agents."""

    from app.db.base import Base
    from app.db.session import engine

    Base.metadata.create_all(engine)

    objective = (
        "Collect frontier AI intelligence for 2026-07-05. "
        "Focus on model releases, research breakthroughs, API changes, "
        "and semiconductor/tech-finance signals. "
    )

    session = SessionLocal()
    try:
        tool_registry = create_default_tool_registry()
        role_registry = create_default_agent_role_registry(
            tool_registry,
            include_development_tools=False,
        )
        model_factory = create_deepseek_model_factory()

        agent_runner = AgentRunner(
            session=session,
            role_registry=role_registry,
            tool_registry=tool_registry,
            model_factory=model_factory,
        )

        harness = DailyRunHarness(
            session=session,
            agent_runner=agent_runner,
            config=HarnessConfig(min_selected_items=1),
        )

        run = harness.create_run(
            report_date=date(2026, 7, 5),
            objective=objective,
            budgets=RunBudgets(max_collect_rounds=2, max_followup_rounds=1, max_writing_rounds=2),
        )
        print(f"\nRun created: {run.id}")

        print("\n=== COLLECT LOOP ===")
        result = harness.run(
            run,
            collect_tasks_by_phase=build_collect_tasks(objective),
            writing_tasks_by_phase=build_writing_tasks(objective),
        )
        session.commit()

        final = result.run
        print("\n=== RESULTS ===")
        print(f"Phase: {final.phase.value}  Status: {final.status.value}")
        print(f"Collect rounds: {final.loop_counters.collect_rounds}")
        print(f"Writing rounds: {final.loop_counters.writing_rounds}")
        print(f"Tool calls: {final.loop_counters.tool_calls}")
        print(f"Model calls: {final.loop_counters.model_calls}")
        print(f"Report ID: {final.report_id}")

        for decision in result.collect_decisions:
            print(f"  Collect: {decision.outcome.value} - {decision.reasoning_summary[:120]}")
        for decision in result.writing_decisions:
            print(f"  Writing: {decision.outcome.value} - {decision.reasoning_summary[:120]}")

        if final.report_id:
            report = DailyReportRepository(session).require(final.report_id)
            print("\n=== REPORT ===")
            print(f"Title: {report.title}")
            print(f"Sections: {len(report.sections)}")
            print(f"Evidence map entries: {len(report.evidence_map)}")
            if report.full_markdown:
                print(f"Markdown length: {len(report.full_markdown)} chars")
                print("\n--- MARKDOWN (first 500 chars) ---")
                print(report.full_markdown[:500])
            assert len(report.sections) > 0, "Report should have at least one section"
            assert report.full_markdown, "Report should have markdown"
        else:
            pytest.fail("No final report was produced")
    finally:
        session.close()
