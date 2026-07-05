"""Top-level daily run harness."""

from __future__ import annotations

import traceback
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.agents import AgentRunner
from app.core.ids import IdPrefix, random_id
from app.domain import RunBudgets, RunPhase, RunState, RunStatus, SourceType, TraceEventType, TraceStatus
from app.domain.base import utc_now
from app.harness.collect import CollectLoopHarness
from app.harness.config import HarnessConfig
from app.harness.context import HarnessContext
from app.harness.decisions import AgentTask, DailyRunResult
from app.harness.exceptions import HarnessError
from app.harness.gates import QualityGateService
from app.harness.writing import WritingLoopHarness
from app.services import ArtifactService, TraceService


class DailyRunHarness:
    """Create, run, and resume Connor.ai daily runs."""

    def __init__(
        self,
        session: Session,
        *,
        agent_runner: AgentRunner | None = None,
        config: HarnessConfig | None = None,
        trace_service: TraceService | None = None,
        artifact_service: ArtifactService | None = None,
    ):
        self.context = HarnessContext(
            session=session,
            agent_runner=agent_runner,
            config=config,
            trace_service=trace_service,
            artifact_service=artifact_service,
        )
        self.gate_service = QualityGateService(self.context.config)
        self.collect_loop = CollectLoopHarness(self.context, gate_service=self.gate_service)
        self.writing_loop = WritingLoopHarness(self.context, gate_service=self.gate_service)

    def create_run(
        self,
        *,
        report_date: date,
        objective: str,
        run_id: str | None = None,
        budgets: RunBudgets | None = None,
        enabled_sources: list[SourceType] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunState:
        """Create and persist a scheduled daily run."""

        run = RunState(
            id=run_id or self._daily_run_id(report_date),
            report_date=report_date,
            objective=objective,
            status=RunStatus.SCHEDULED,
            phase=RunPhase.INITIALIZE,
            budgets=budgets or RunBudgets(),
            enabled_sources=enabled_sources or [],
            metadata=metadata or {},
            created_at=utc_now(),
        )
        self.context.runs.add(run)
        self.context.trace_service.record_event(
            run_id=run.id,
            phase=RunPhase.INITIALIZE,
            event_type=TraceEventType.RUN_STARTED,
            status=TraceStatus.STARTED,
            summary="Daily run created by Connor harness.",
            input_payload=run.model_dump(mode="json"),
            metadata={"harness": True},
        )
        self.context.session.flush()
        return run

    def run(
        self,
        run: RunState,
        *,
        collect_tasks_by_phase: dict[RunPhase, list[AgentTask]] | None = None,
        writing_tasks_by_phase: dict[RunPhase, list[AgentTask]] | None = None,
    ) -> DailyRunResult:
        """Run collect and writing loops from the provided run state."""

        if run.status == RunStatus.FAILED:
            raise HarnessError("failed runs cannot be resumed directly; reset the run explicitly first")

        collect_decisions = []
        writing_decisions = []
        try:
            active_run = run
            if active_run.status == RunStatus.SCHEDULED:
                active_run = self.context.transition_run(
                    active_run,
                    phase=RunPhase.COLLECT_PLANNING,
                    status=RunStatus.RUNNING,
                    summary="Daily run started; entering collect loop.",
                )

            if (
                active_run.phase in {
                    RunPhase.INITIALIZE,
                    RunPhase.COLLECT_PLANNING,
                    RunPhase.SCOUTING,
                    RunPhase.CLUSTERING,
                    RunPhase.EVALUATING,
                    RunPhase.EVALUATION_GATE,
                    RunPhase.FOLLOWUP,
                    RunPhase.WATCHLIST_UPDATE,
                }
                and active_run.status == RunStatus.RUNNING
            ):
                active_run, collect_decisions = self.collect_loop.run(
                    active_run,
                    tasks_by_phase=collect_tasks_by_phase,
                )

            if active_run.phase == RunPhase.WRITING and active_run.status == RunStatus.RUNNING:
                active_run, writing_decisions = self.writing_loop.run(
                    active_run,
                    tasks_by_phase=writing_tasks_by_phase,
                )

            return DailyRunResult(
                run=active_run,
                collect_decisions=collect_decisions,
                writing_decisions=writing_decisions,
                final_report_id=active_run.report_id,
                metadata={
                    "collect_outcomes": [decision.outcome.value for decision in collect_decisions],
                    "writing_outcomes": [decision.outcome.value for decision in writing_decisions],
                },
            )
        except Exception as exc:
            latest_run = self.context.runs.require(run.id)
            error_summary = str(exc) or type(exc).__name__
            self.context.fail_run(
                latest_run,
                error_summary=error_summary,
                error_detail=traceback.format_exc(),
                phase=latest_run.phase,
            )
            raise

    def resume(
        self,
        run_id: str,
        *,
        collect_tasks_by_phase: dict[RunPhase, list[AgentTask]] | None = None,
        writing_tasks_by_phase: dict[RunPhase, list[AgentTask]] | None = None,
    ) -> DailyRunResult:
        """Resume a persisted run by id."""

        run = self.context.runs.require(run_id)
        if run.status == RunStatus.FAILED:
            raise HarnessError("failed runs cannot be resumed directly; reset the run explicitly first")
        return self.run(
            run,
            collect_tasks_by_phase=collect_tasks_by_phase,
            writing_tasks_by_phase=writing_tasks_by_phase,
        )

    @staticmethod
    def _daily_run_id(report_date: date) -> str:
        return random_id(IdPrefix.RUN, parts=[report_date.isoformat()], length=16)
