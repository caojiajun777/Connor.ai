"""Connor.ai daily-intelligence CLI.

Run a full end-to-end intelligence cycle with real LLM-powered agents:

    python -m app.cli run --date 2026-07-05

Requirements:
    CONNOR_DEEPSEEK_API_KEY (set in .env or environment)
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import date
from pathlib import Path
from typing import Any

from app.agents import (
    AgentRunner,
    create_deepseek_model_factory,
    create_default_agent_role_registry,
)
from app.clusterer.tasks import ClusterTaskFactory
from app.config import get_settings
from app.db.session import SessionLocal
from app.domain import AgentRole, RunBudgets, RunPhase, RunStatus
from app.evaluators.tasks import EvaluatorTaskFactory
from app.harness import DailyRunHarness, HarnessConfig
from app.harness.decisions import AgentTask
from app.repositories import RunRepository
from app.scouts.tasks import ScoutTaskFactory
from app.tools import create_default_tool_registry
from app.watchlist.tasks import WatchlistTaskFactory


def build_collect_tasks(objective: str) -> dict[RunPhase, list[AgentTask]]:
    """Build one Scout -> Clusterer -> Evaluator -> Watchlist task set."""

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
    """Build Writer -> Reviewer -> Editor -> Final Reviewer task set."""

    return {
        RunPhase.WRITING: [
            AgentTask(
                agent_role=AgentRole.WRITER,
                phase=RunPhase.WRITING,
                task=(
                    "Write a structured daily intelligence report from the selected clusters, "
                    "evaluations, evidence, watchlist, and thread context. "
                    "Produce report_drafts with sections and evidence_map coverage. "
                    "Early Signals must stay explicitly uncertain; never write them as "
                    "confirmed facts. Write human-facing narrative fields in Simplified "
                    "Chinese while preserving English names, tickers, model names, APIs, "
                    "URLs, and paper titles. "
                    f"Objective: {objective}"
                ),
                context={
                    "report_format": "Produce title, overview_judgments, tomorrow_focus, and "
                    "at least one ReportSection per selected cluster category. "
                    "Each report item requires title, core_information, why_it_matters, "
                    "potential_impact, evidence_ids, cluster_ids, and an explicit "
                    "uncertainty_label for early-signal items."
                },
            )
        ],
        RunPhase.REVIEWING: [
            AgentTask(
                agent_role=AgentRole.REVIEWER,
                phase=RunPhase.REVIEWING,
                task=(
                    "Review the draft report. Check: (1) early signals are not written as "
                    "confirmed facts, (2) every report item has evidence coverage, "
                    "(3) Markdown matches the structured JSON sections, "
                    "(4) tech-finance items include data, tickers, and impact chain. "
                    "(5) human-facing narrative body is written in Simplified Chinese. "
                    "Return review_drafts with specific issues and a clear decision. "
                    f"Objective: {objective}"
                ),
            )
        ],
        RunPhase.EDITING: [
            AgentTask(
                agent_role=AgentRole.EDITOR,
                phase=RunPhase.EDITING,
                task=(
                    "Revise the draft report based on the latest review issues. "
                    "Fix early-signal language, evidence gaps, and section consistency. "
                    "Rewrite human-facing narrative fields in Simplified Chinese. "
                    "Return revised_report_drafts. Do not add facts beyond evidence. "
                    f"Objective: {objective}"
                ),
            )
        ],
        RunPhase.FINAL_REVIEW: [
            AgentTask(
                agent_role=AgentRole.REVIEWER,
                phase=RunPhase.FINAL_REVIEW,
                task=(
                    "Final review of the revised report. Verify all reviewer issues "
                    "have been addressed and the human-facing body is in Simplified Chinese. "
                    "Return review_drafts with decision PASS "
                    "if the report is ready to finalize, REVISE if issues remain. "
                    f"Objective: {objective}"
                ),
            )
        ],
    }


def cmd_run(args: argparse.Namespace) -> int:
    """Execute a full daily intelligence cycle."""

    settings = get_settings()
    if not settings.deepseek_api_key:
        print("ERROR: CONNOR_DEEPSEEK_API_KEY is not set.", file=sys.stderr)
        print("Create a .env file or set the environment variable.", file=sys.stderr)
        return 1

    report_date = args.date or date.today()
    objective = args.objective or (
        "Collect frontier AI, semiconductor, and tech-finance intelligence "
        "for the daily Connor.ai report. Focus on model releases, API changes, "
        "research breakthroughs, infrastructure signals, and market-moving events."
    )

    print("=" * 50)
    print("Connor.ai Daily Intelligence Cycle")
    print(f"Date: {report_date.isoformat()}")
    print("=" * 50)

    from app.db.base import Base
    from app.db.session import get_engine

    Base.metadata.create_all(get_engine())

    print("Bootstrapping pipeline ...")
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
            config=HarnessConfig(
                min_selected_items=2,
                min_report_body_items=2,
                commit_checkpoints=True,
            ),
            model_factory=model_factory,
        )
        print("  Tool registry, role registry, and model factory are ready.")

        print(f"Creating daily run for {report_date.isoformat()} ...")
        run = harness.create_run(
            report_date=report_date,
            objective=objective,
            budgets=RunBudgets(
                max_collect_rounds=3,
                max_followup_rounds=2,
                max_writing_rounds=3,
            ),
        )
        print(f"  Run created: {run.id}")

        print("Building agent tasks ...")
        collect_tasks = build_collect_tasks(objective)
        writing_tasks = build_writing_tasks(objective)

        collect_roles = {
            task.agent_role.value for tasks in collect_tasks.values() for task in tasks
        }
        writing_roles = {
            task.agent_role.value for tasks in writing_tasks.values() for task in tasks
        }
        print(f"  Collect phase: {len(collect_roles)} roles across {len(collect_tasks)} phases")
        print(f"  Writing phase: {len(writing_roles)} roles across {len(writing_tasks)} phases")

        print()
        print("=" * 50)
        print("COLLECT LOOP")
        print("=" * 50)

        result = harness.run(
            run,
            collect_tasks_by_phase=collect_tasks,
            writing_tasks_by_phase=writing_tasks,
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        print(f"\nRun failed: {exc}")
        traceback.print_exc()
        session.close()
        return 1

    final_run = result.run
    print()
    print("=" * 50)
    print("RESULTS")
    print("=" * 50)
    print(f"  Final phase      : {final_run.phase.value}")
    print(f"  Status           : {final_run.status.value}")
    print(f"  Collect rounds   : {final_run.loop_counters.collect_rounds}")
    print(f"  Followup rounds  : {final_run.loop_counters.followup_rounds}")
    print(f"  Writing rounds   : {final_run.loop_counters.writing_rounds}")
    print(f"  Tool calls       : {final_run.loop_counters.tool_calls}")
    print(f"  Model calls      : {final_run.loop_counters.model_calls}")
    print(f"  Report ID        : {final_run.report_id or 'N/A'}")

    print()
    print("  Collect decisions:")
    for decision in result.collect_decisions:
        print(f"    - {decision.outcome.value}: {decision.reasoning_summary[:100]}")

    print()
    print("  Writing decisions:")
    for decision in result.writing_decisions:
        print(f"    - {decision.outcome.value}: {decision.reasoning_summary[:100]}")

    if final_run.report_id and args.output:
        _save_report(session, final_run.report_id, args.output)
    elif final_run.report_id:
        print(f"\n  Report available via: GET /reports/{final_run.report_id}")
    else:
        print("\n  No final report was produced. The run may have paused or failed.")

    if getattr(args, "cleanup", False):
        from app.repositories.cleanup import cleanup_expired_data

        print()
        cleanup_result = cleanup_expired_data(session)
        for key, value in sorted(cleanup_result.items()):
            if value:
                print(f"  cleanup: {key} = {value}")

    session.close()
    return 0 if final_run.status == RunStatus.COMPLETED else 1


def _save_report(session: Any, report_id: str, output_dir: str) -> None:
    """Write the final report to disk as both markdown and JSON."""

    from app.repositories import DailyReportRepository

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    try:
        report = DailyReportRepository(session).require(report_id)
    except LookupError:
        print(f"  Report {report_id} not found in database.")
        return

    if report.full_markdown:
        md_path = out / f"report-{report.report_date.isoformat()}.md"
        md_path.write_text(report.full_markdown, encoding="utf-8")
        print(f"  Markdown saved to {md_path}")

    json_path = out / f"report-{report.report_date.isoformat()}.json"
    json_path.write_text(
        json.dumps(report.full_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  JSON saved to {json_path}")

    if report.evidence_map:
        ev_path = out / f"evidence-map-{report.report_date.isoformat()}.json"
        ev_path.write_text(
            json.dumps(
                [entry.model_dump(mode="json") for entry in report.evidence_map],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"  Evidence map saved to {ev_path}")


def cmd_status(_args: argparse.Namespace) -> int:
    """Show the latest run status."""

    session = SessionLocal()
    try:
        runs = RunRepository(session).list_all()
        if not runs:
            print("No runs found.")
            return 0
        latest = runs[-1]
        state = RunRepository(session).get_full_state(latest.id)
        print(f"Latest run: {latest.id}")
        print(f"  Date       : {latest.report_date.isoformat()}")
        print(f"  Phase      : {latest.phase.value}")
        print(f"  Status     : {latest.status.value}")
        print(f"  Evidence   : {len(state.evidence)}")
        print(f"  Candidates : {len(state.candidates)}")
        print(f"  Clusters   : {len(state.clusters)}")
        print(f"  Evaluations: {len(state.evaluations)}")
        print(f"  Watchlist  : {len(state.watchlist)}")
        print(f"  Reports    : {len(state.reports)}")
        if latest.report_id:
            print(f"  Report ID  : {latest.report_id}")
        if latest.error_summary:
            print(f"  Error      : {latest.error_summary}")

        # X cookie health
        from app.tools.cookie_health import check_x_cookie_health  # noqa: E402

        cookie = check_x_cookie_health()
        print(f"  X Cookie   : {cookie['status']} — {cookie['message']}")

        return 0
    finally:
        session.close()


def cmd_cleanup(args: argparse.Namespace) -> int:
    """Clean up expired data from the database."""
    from app.repositories.cleanup import cleanup_expired_data

    session = SessionLocal()
    try:
        dry_run = getattr(args, "dry_run", False)
        result = cleanup_expired_data(session, dry_run=dry_run)
        if dry_run:
            print("Dry run — would delete/archive:")
        for key, value in sorted(result.items()):
            print(f"  {key}: {value}")
        if not dry_run:
            print("Cleanup complete.")
        return 0
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Connor.ai traceable multi-agent daily intelligence.",
    )
    sub = parser.add_subparsers(dest="command")

    run_parser = sub.add_parser("run", help="Execute a full daily intelligence cycle")
    run_parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=None,
        help="Report date (YYYY-MM-DD). Defaults to today.",
    )
    run_parser.add_argument(
        "--objective",
        type=str,
        default=None,
        help="Custom intelligence objective for this run.",
    )
    run_parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Directory to save the final report (markdown + JSON).",
    )
    run_parser.add_argument(
        "--cleanup",
        action="store_true",
        default=False,
        help="Run data retention cleanup after the intelligence cycle.",
    )

    sub.add_parser("status", help="Show the latest run status")

    cleanup_parser = sub.add_parser("cleanup", help="Clean up expired data")
    cleanup_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Preview what would be deleted without actually deleting.",
    )

    args = parser.parse_args()

    if args.command == "run":
        return cmd_run(args)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "cleanup":
        return cmd_cleanup(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
