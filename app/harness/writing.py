"""Writing loop harness."""

from __future__ import annotations

from collections.abc import Mapping

from app.agents import AgentRunRequest
from app.domain import (
    ArtifactKind,
    DailyReport,
    ReportStatus,
    RunPhase,
    RunState,
    RunStatus,
    TraceEventType,
    TraceStatus,
)
from app.domain.base import utc_now
from app.harness.context import HarnessContext
from app.harness.decisions import AgentTask, WritingGateDecision, WritingGateOutcome
from app.harness.exceptions import HarnessError
from app.harness.gates import QualityGateService
from app.repositories import DailyReportRepository
from app.repositories.runs import FullRunState
from app.writing import WritingOutputMaterializer, WritingTaskFactory


WRITING_PHASES = {
    RunPhase.WRITING,
    RunPhase.REVIEWING,
    RunPhase.EDITING,
    RunPhase.FINAL_REVIEW,
}


class WritingLoopHarness:
    """Run and gate the Connor writing/review/revision loop."""

    def __init__(
        self,
        context: HarnessContext,
        *,
        gate_service: QualityGateService | None = None,
    ):
        self.context = context
        self.gate_service = gate_service or QualityGateService(context.config)
        self.reports = DailyReportRepository(context.session)
        self.materializer = WritingOutputMaterializer(context)

    def run(
        self,
        run: RunState,
        *,
        tasks_by_phase: Mapping[RunPhase, list[AgentTask]] | None = None,
    ) -> tuple[RunState, list[WritingGateDecision]]:
        """Execute writing rounds until finalization, manual review, or failure."""

        decisions: list[WritingGateDecision] = []
        tasks_by_phase = tasks_by_phase or self._tasks_from_run_metadata(run)

        while True:
            if run.loop_counters.writing_rounds >= run.budgets.max_writing_rounds:
                decision = WritingGateDecision(
                    outcome=WritingGateOutcome.NEEDS_MANUAL_REVIEW
                    if self.context.config.manual_review_on_failure
                    else WritingGateOutcome.FAIL,
                    reasoning_summary="Writing budget exhausted before final report passed review.",
                    risk_flags=["writing_budget_exhausted"],
                    metrics={"writing_rounds": run.loop_counters.writing_rounds},
                )
                self._record_gate_decision(run, decision)
                run = self._apply_decision(run, decision)
                decisions.append(decision)
                return run, decisions

            run = self._start_writing_round(run)
            full_state = self.context.runs.get_full_state(run.id)

            if not full_state.reports:
                self._execute_phase_tasks(run, RunPhase.WRITING, tasks_by_phase, full_state=full_state)
                full_state = self.context.runs.get_full_state(run.id)

            if full_state.reports and not full_state.review_results:
                self._execute_phase_tasks(run, RunPhase.REVIEWING, tasks_by_phase, full_state=full_state)
                full_state = self.context.runs.get_full_state(run.id)

            decision = self.gate_service.evaluate_writing(full_state)
            self._record_gate_decision(run, decision)
            if self.context.config.archive_gate_snapshots:
                self.context.archive_snapshot(
                    run_id=run.id,
                    phase=RunPhase.REVIEWING,
                    label=f"writing_gate_round_{run.loop_counters.writing_rounds}",
                    payload=decision.model_dump(mode="json"),
                )

            decisions.append(decision)
            run = self._apply_decision(run, decision)

            if decision.outcome == WritingGateOutcome.REVISE:
                if run.loop_counters.writing_rounds >= run.budgets.max_writing_rounds:
                    exhausted = WritingGateDecision(
                        outcome=WritingGateOutcome.NEEDS_MANUAL_REVIEW
                        if self.context.config.manual_review_on_failure
                        else WritingGateOutcome.FAIL,
                        reasoning_summary="Writing budget exhausted mid-round before revision could complete.",
                        risk_flags=["writing_budget_exhausted"],
                        metrics={"writing_rounds": run.loop_counters.writing_rounds},
                    )
                    self._record_gate_decision(run, exhausted)
                    run = self._apply_decision(run, exhausted)
                    decisions.append(exhausted)
                    return run, decisions
                self._execute_phase_tasks(run, RunPhase.EDITING, tasks_by_phase, full_state=full_state)
                review_phase = (
                    RunPhase.FINAL_REVIEW
                    if tasks_by_phase.get(RunPhase.FINAL_REVIEW)
                    else RunPhase.REVIEWING
                )
                # Transition the run phase to match before executing review
                # tasks so the persisted run record stays consistent.
                if review_phase == RunPhase.FINAL_REVIEW:
                    latest = self.context.runs.require(run.id)
                    run = latest.model_copy(
                        update={"phase": RunPhase.FINAL_REVIEW, "updated_at": utc_now()}
                    )
                    self.context.runs.add(run)
                    self.context.session.flush()
                self._execute_phase_tasks(run, review_phase, tasks_by_phase, full_state=full_state)
                continue

            if decision.outcome in {
                WritingGateOutcome.FINALIZE,
                WritingGateOutcome.REOPEN_COLLECT,
                WritingGateOutcome.NEEDS_MANUAL_REVIEW,
                WritingGateOutcome.FAIL,
            }:
                return run, decisions

            if decision.outcome == WritingGateOutcome.REVIEW_DRAFT:
                review_tasks = tasks_by_phase.get(RunPhase.REVIEWING, [])
                if not review_tasks:
                    no_reviewer = WritingGateDecision(
                        outcome=WritingGateOutcome.NEEDS_MANUAL_REVIEW
                        if self.context.config.manual_review_on_failure
                        else WritingGateOutcome.FAIL,
                        reasoning_summary=(
                            "Gate returned REVIEW_DRAFT but no review tasks are configured. "
                            "Add a reviewer task or enable manual review."
                        ),
                        risk_flags=["missing_review_tasks"],
                        metrics={"writing_rounds": run.loop_counters.writing_rounds},
                    )
                    self._record_gate_decision(run, no_reviewer)
                    run = self._apply_decision(run, no_reviewer)
                    decisions.append(no_reviewer)
                    return run, decisions
                self._execute_phase_tasks(run, RunPhase.REVIEWING, tasks_by_phase, full_state=full_state)
                continue

    def _start_writing_round(self, run: RunState) -> RunState:
        self.context.session.flush()
        counters = run.loop_counters.model_copy(
            update={"writing_rounds": run.loop_counters.writing_rounds + 1}
        )
        next_run = run.model_copy(
            update={
                "phase": RunPhase.WRITING,
                "status": RunStatus.RUNNING,
                "loop_counters": counters,
                "updated_at": utc_now(),
            }
        )
        self.context.runs.add(next_run)
        self.context.trace_service.record_event(
            run_id=run.id,
            phase=RunPhase.WRITING,
            event_type=TraceEventType.PHASE_STARTED,
            status=TraceStatus.STARTED,
            summary=f"Writing round {counters.writing_rounds} started.",
            metadata={"writing_round": counters.writing_rounds, "harness": True},
        )
        self.context.session.flush()
        return next_run

    def _execute_phase_tasks(
        self,
        run: RunState,
        phase: RunPhase,
        tasks_by_phase: Mapping[RunPhase, list[AgentTask]],
        *,
        full_state: FullRunState | None = None,
    ) -> None:
        tasks = list(tasks_by_phase.get(phase, []))
        if not tasks:
            return
        if phase not in WRITING_PHASES:
            raise HarnessError(f"{phase.value} is not a writing-loop phase")
        if self.context.agent_runner is None:
            raise HarnessError(f"{phase.value} tasks require an AgentRunner")

        self.context.trace_service.record_event(
            run_id=run.id,
            phase=phase,
            event_type=TraceEventType.PHASE_STARTED,
            status=TraceStatus.STARTED,
            summary=f"{phase.value} phase started with {len(tasks)} task(s).",
            metadata={"task_count": len(tasks), "harness": True},
        )

        tool_call_count = 0
        for task in tasks:
            if task.phase != phase:
                raise HarnessError(f"task phase {task.phase.value} does not match {phase.value}")
            result = self.context.agent_runner.run(
                AgentRunRequest(
                    run_id=run.id,
                    phase=phase,
                    agent_role=task.agent_role,
                    task=task.task,
                    context=self._build_task_context(run, phase, task.context, full_state=full_state),
                )
            )
            tool_call_count += len(result.tool_results)
            if self.context.config.materialize_writing_outputs:
                self.materializer.materialize(
                    run=run,
                    phase=phase,
                    agent_role=task.agent_role,
                    result=result,
                )

        latest_run = self.context.runs.require(run.id)
        counters = latest_run.loop_counters.model_copy(
            update={
                "tool_calls": latest_run.loop_counters.tool_calls + tool_call_count,
                "model_calls": latest_run.loop_counters.model_calls + len(tasks),
            }
        )
        self.context.runs.add(latest_run.model_copy(update={"loop_counters": counters}))
        self.context.complete_phase(
            run_id=run.id,
            phase=phase,
            summary=f"{phase.value} phase completed.",
        )

    def _build_task_context(
        self,
        run: RunState,
        phase: RunPhase,
        task_context: dict,
        *,
        full_state: FullRunState | None = None,
    ) -> dict:
        context = {
            **task_context,
            "run_id": run.id,
            "report_date": run.report_date.isoformat(),
            "writing_round": run.loop_counters.writing_rounds,
            "selected_cluster_ids": run.selected_cluster_ids,
        }
        # Reuse the caller's already-fetched FullRunState when available;
        # only fetch it here as a fallback for callers without one.
        if full_state is None:
            full_state = self.context.runs.get_full_state(run.id)
        if phase == RunPhase.WRITING:
            context["writing_context"] = WritingTaskFactory.writer_context(full_state)
        if phase in {RunPhase.REVIEWING, RunPhase.FINAL_REVIEW}:
            context["review_context"] = WritingTaskFactory.reviewer_context(full_state)
        if phase == RunPhase.EDITING:
            context["editor_context"] = WritingTaskFactory.editor_context(full_state)
        return context

    def _record_gate_decision(self, run: RunState, decision: WritingGateDecision) -> None:
        self.context.trace_service.record_event(
            run_id=run.id,
            phase=RunPhase.REVIEWING,
            event_type=TraceEventType.GATE_DECISION,
            status=TraceStatus.SUCCEEDED,
            summary=f"Writing gate decision: {decision.outcome.value}.",
            reasoning_summary=decision.reasoning_summary,
            output_payload=decision.model_dump(mode="json"),
            metadata={"outcome": decision.outcome.value, "harness": True},
        )
        self.context.session.flush()

    def _apply_decision(self, run: RunState, decision: WritingGateDecision) -> RunState:
        latest_run = self.context.runs.require(run.id)
        metadata = {**latest_run.metadata, "last_writing_gate": decision.model_dump(mode="json")}

        if decision.outcome == WritingGateOutcome.FINALIZE:
            report = self._finalize_report(decision.report_id)
            finalized_run = latest_run.model_copy(
                update={
                    "phase": RunPhase.FINALIZED,
                    "status": RunStatus.COMPLETED,
                    "report_id": report.id,
                    "metadata": metadata,
                    "updated_at": utc_now(),
                }
            )
            self.context.runs.add(finalized_run)
            self.context.trace_service.record_event(
                run_id=latest_run.id,
                phase=RunPhase.FINALIZED,
                event_type=TraceEventType.REPORT_FINALIZED,
                status=TraceStatus.SUCCEEDED,
                summary="Final report accepted by writing gate.",
                created_objects=[report],
                output_payload=report.model_dump(mode="json"),
                metadata={"report_id": report.id, "harness": True},
            )
            self.context.archive_snapshot(
                run_id=latest_run.id,
                phase=RunPhase.FINALIZED,
                label="final_report",
                payload=report.model_dump(mode="json"),
                kind=ArtifactKind.REPORT_SNAPSHOT,
            )
            self.context.session.flush()
            return finalized_run

        if decision.outcome == WritingGateOutcome.REVISE:
            counters = latest_run.loop_counters.model_copy(
                update={"review_rounds": latest_run.loop_counters.review_rounds + 1}
            )
            revised_run = latest_run.model_copy(
                update={
                    "phase": RunPhase.EDITING,
                    "loop_counters": counters,
                    "metadata": metadata,
                    "updated_at": utc_now(),
                }
            )
            self.context.runs.add(revised_run)
            self.context.session.flush()
            return revised_run

        if decision.outcome == WritingGateOutcome.REOPEN_COLLECT:
            reopened = latest_run.model_copy(
                update={
                    "phase": RunPhase.FOLLOWUP,
                    "status": RunStatus.RUNNING,
                    "metadata": {
                        **metadata,
                        "reopen_collect_reasons": decision.reopen_collect_reasons,
                    },
                    "updated_at": utc_now(),
                }
            )
            self.context.runs.add(reopened)
            self.context.session.flush()
            return reopened

        if decision.outcome == WritingGateOutcome.NEEDS_MANUAL_REVIEW:
            paused = latest_run.model_copy(
                update={
                    "phase": RunPhase.REVIEWING,
                    "status": RunStatus.PAUSED,
                    "metadata": {**metadata, "manual_review_required": True},
                    "updated_at": utc_now(),
                }
            )
            self.context.runs.add(paused)
            self.context.session.flush()
            return paused

        if decision.outcome == WritingGateOutcome.FAIL:
            return self.context.fail_run(
                latest_run,
                phase=RunPhase.REVIEWING,
                error_summary=decision.reasoning_summary,
            )

        return latest_run.model_copy(update={"metadata": metadata, "updated_at": utc_now()})

    def _finalize_report(self, report_id: str) -> DailyReport:
        report = self.reports.require(report_id)
        timeline_ids = report.trace_timeline_ids or [
            event.id for event in self.context.trace_service.reconstruct_timeline(report.run_id).events
        ]
        finalized = report.model_copy(
            update={
                "status": ReportStatus.FINAL,
                "trace_timeline_ids": timeline_ids,
                "updated_at": utc_now(),
            }
        )
        self.reports.add(finalized)
        return finalized

    @staticmethod
    def _tasks_from_run_metadata(run: RunState) -> dict[RunPhase, list[AgentTask]]:
        raw_tasks = run.metadata.get("writing_tasks", {})
        tasks: dict[RunPhase, list[AgentTask]] = {}
        if not isinstance(raw_tasks, dict):
            return tasks
        for phase_value, phase_tasks in raw_tasks.items():
            phase = RunPhase(phase_value)
            tasks[phase] = [AgentTask.model_validate(task) for task in phase_tasks]
        return tasks
