"""Collect loop harness."""

from __future__ import annotations

from collections.abc import Mapping

from app.agents import AgentRunRequest
from app.clusterer.materialization import ClusterOutputMaterializer
from app.clusterer.tasks import ClusterTaskFactory
from app.domain import AgentRole, RunPhase, RunState, RunStatus, TraceEventType, TraceStatus
from app.domain.base import utc_now
from app.evaluators.materialization import EvaluatorOutputMaterializer
from app.evaluators.tasks import EvaluatorTaskFactory
from app.harness.context import HarnessContext
from app.harness.decisions import AgentTask, CollectGateDecision, CollectGateOutcome
from app.harness.exceptions import HarnessError
from app.harness.gates import QualityGateService
from app.harness.materialization import ScoutOutputMaterializer
from app.watchlist.lifecycle import WatchlistLifecycleService
from app.watchlist.materialization import WatchlistOutputMaterializer
from app.watchlist.tasks import WatchlistTaskFactory


COLLECT_TASK_LIMITS = {
    RunPhase.SCOUTING: "max_scout_tasks_per_round",
    RunPhase.CLUSTERING: "max_cluster_tasks_per_round",
    RunPhase.EVALUATING: "max_evaluator_tasks_per_round",
    RunPhase.WATCHLIST_UPDATE: "max_watchlist_tasks_per_round",
}


class CollectLoopHarness:
    """Run and gate the Connor collect loop."""

    def __init__(
        self,
        context: HarnessContext,
        *,
        gate_service: QualityGateService | None = None,
    ):
        self.context = context
        self.gate_service = gate_service or QualityGateService(context.config)
        self.materializer = ScoutOutputMaterializer(context)
        self.cluster_materializer = ClusterOutputMaterializer(context)
        self.evaluator_materializer = EvaluatorOutputMaterializer(context)
        self.watchlist_materializer = WatchlistOutputMaterializer(context)
        self.watchlist_lifecycle = WatchlistLifecycleService(context)

    def run(
        self,
        run: RunState,
        *,
        tasks_by_phase: Mapping[RunPhase, list[AgentTask]] | None = None,
    ) -> tuple[RunState, list[CollectGateDecision]]:
        """Execute collect rounds until writing, manual review, or failure."""

        decisions: list[CollectGateDecision] = []
        tasks_by_phase = tasks_by_phase or self._tasks_from_run_metadata(run)

        while True:
            if run.loop_counters.collect_rounds >= run.budgets.max_collect_rounds:
                decision = self.gate_service.evaluate_collect(self.context.runs.get_full_state(run.id))
                decision = self._force_exhausted_decision(decision)
                run = self._apply_decision(run, decision)
                decisions.append(decision)
                return run, decisions

            run = self._start_collect_round(run)
            self._execute_phase_tasks(run, RunPhase.SCOUTING, tasks_by_phase)
            self._execute_phase_tasks(run, RunPhase.CLUSTERING, tasks_by_phase)
            self._execute_phase_tasks(run, RunPhase.EVALUATING, tasks_by_phase)
            self._execute_phase_tasks(run, RunPhase.WATCHLIST_UPDATE, tasks_by_phase)

            full_state = self.context.runs.get_full_state(run.id)
            decision = self.gate_service.evaluate_collect(full_state)
            self._record_gate_decision(run, decision)
            if self.context.config.archive_gate_snapshots:
                self.context.archive_snapshot(
                    run_id=run.id,
                    phase=RunPhase.EVALUATION_GATE,
                    label=f"collect_gate_round_{run.loop_counters.collect_rounds}",
                    payload=decision.model_dump(mode="json"),
                )

            decisions.append(decision)
            run = self._apply_decision(run, decision)

            if decision.outcome in {
                CollectGateOutcome.ENTER_WRITING,
                CollectGateOutcome.NEEDS_MANUAL_REVIEW,
                CollectGateOutcome.FAIL,
            }:
                return run, decisions

    def _start_collect_round(self, run: RunState) -> RunState:
        self.context.session.flush()
        counters = run.loop_counters.model_copy(
            update={"collect_rounds": run.loop_counters.collect_rounds + 1}
        )
        next_run = run.model_copy(
            update={
                "phase": RunPhase.COLLECT_PLANNING,
                "status": RunStatus.RUNNING,
                "loop_counters": counters,
                "updated_at": utc_now(),
            }
        )
        self.context.runs.add(next_run)
        self.context.trace_service.record_event(
            run_id=run.id,
            phase=RunPhase.COLLECT_PLANNING,
            event_type=TraceEventType.PHASE_STARTED,
            status=TraceStatus.STARTED,
            summary=f"Collect round {counters.collect_rounds} started.",
            metadata={"collect_round": counters.collect_rounds, "harness": True},
        )
        self.context.session.flush()
        return next_run

    def _execute_phase_tasks(
        self,
        run: RunState,
        phase: RunPhase,
        tasks_by_phase: Mapping[RunPhase, list[AgentTask]],
    ) -> None:
        tasks = list(tasks_by_phase.get(phase, []))
        limit_name = COLLECT_TASK_LIMITS[phase]
        limit = getattr(self.context.config, limit_name)
        if len(tasks) > limit:
            raise HarnessError(f"{phase.value} has {len(tasks)} task(s), limit is {limit}")

        self.context.trace_service.record_event(
            run_id=run.id,
            phase=phase,
            event_type=TraceEventType.PHASE_STARTED,
            status=TraceStatus.STARTED,
            summary=f"{phase.value} phase started with {len(tasks)} task(s).",
            metadata={"task_count": len(tasks), "harness": True},
        )

        if tasks and self.context.agent_runner is None:
            raise HarnessError(f"{phase.value} tasks require an AgentRunner")

        if phase == RunPhase.WATCHLIST_UPDATE and self.context.config.expire_due_watchlist_items:
            self.watchlist_lifecycle.expire_due_items(run=run, phase=phase)

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
                    context=self._build_task_context(run, phase, task.context),
                )
            )
            tool_call_count += len(result.tool_results)
            if phase == RunPhase.SCOUTING and self.context.config.materialize_scout_candidates:
                self.materializer.materialize(
                    run=run,
                    phase=phase,
                    agent_role=task.agent_role,
                    result=result,
                    bootstrap_cluster_and_evaluation=self._should_bootstrap_single_agent(
                        tasks_by_phase
                    ),
                )
            if phase == RunPhase.CLUSTERING and self.context.config.materialize_clusterer_outputs:
                self.cluster_materializer.materialize(
                    run=run,
                    phase=phase,
                    agent_role=task.agent_role,
                    result=result,
                    bootstrap_evaluations=self._should_bootstrap_clusterer_evaluations(
                        tasks_by_phase
                    ),
                )
            if phase == RunPhase.EVALUATING and self.context.config.materialize_evaluator_outputs:
                self.evaluator_materializer.materialize(
                    run=run,
                    phase=phase,
                    agent_role=task.agent_role,
                    result=result,
                )
            if phase == RunPhase.WATCHLIST_UPDATE and self.context.config.materialize_watchlist_outputs:
                self.watchlist_materializer.materialize(
                    run=run,
                    phase=phase,
                    agent_role=task.agent_role,
                    result=result,
                )

        if (
            phase == RunPhase.WATCHLIST_UPDATE
            and not tasks
            and self.context.config.auto_materialize_watchlist_from_evaluations
        ):
            self.watchlist_lifecycle.sync_evaluation_memory(run=run, phase=phase)

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

    def _should_bootstrap_single_agent(
        self,
        tasks_by_phase: Mapping[RunPhase, list[AgentTask]],
    ) -> bool:
        return (
            self.context.config.bootstrap_single_agent_clusters
            and self.context.config.bootstrap_single_agent_evaluations
            and not tasks_by_phase.get(RunPhase.CLUSTERING)
            and not tasks_by_phase.get(RunPhase.EVALUATING)
        )

    def _should_bootstrap_clusterer_evaluations(
        self,
        tasks_by_phase: Mapping[RunPhase, list[AgentTask]],
    ) -> bool:
        return (
            self.context.config.bootstrap_single_agent_evaluations
            and not tasks_by_phase.get(RunPhase.EVALUATING)
        )

    def _build_task_context(
        self,
        run: RunState,
        phase: RunPhase,
        task_context: dict,
    ) -> dict:
        context = {
            **task_context,
            "run_id": run.id,
            "report_date": run.report_date.isoformat(),
            "collect_round": run.loop_counters.collect_rounds,
        }
        if phase == RunPhase.CLUSTERING:
            full_state = self.context.runs.get_full_state(run.id)
            context["candidate_context"] = ClusterTaskFactory.candidate_context(
                candidates=full_state.candidates,
                evidence=full_state.evidence,
            )
        if phase == RunPhase.EVALUATING:
            full_state = self.context.runs.get_full_state(run.id)
            context["cluster_context"] = EvaluatorTaskFactory.cluster_context(
                clusters=full_state.clusters,
                candidates=full_state.candidates,
                evidence=full_state.evidence,
            )
        if phase == RunPhase.WATCHLIST_UPDATE:
            full_state = self.context.runs.get_full_state(run.id)
            context["memory_context"] = WatchlistTaskFactory.memory_context(
                evaluations=full_state.evaluations,
                clusters=full_state.clusters,
                candidates=full_state.candidates,
                evidence=full_state.evidence,
                watchlist=full_state.watchlist,
                archives=full_state.archives,
                threads=full_state.threads,
            )
        return context

    def _record_gate_decision(self, run: RunState, decision: CollectGateDecision) -> None:
        self.context.trace_service.record_event(
            run_id=run.id,
            phase=RunPhase.EVALUATION_GATE,
            event_type=TraceEventType.GATE_DECISION,
            status=TraceStatus.SUCCEEDED,
            summary=f"Collect gate decision: {decision.outcome.value}.",
            reasoning_summary=decision.reasoning_summary,
            output_payload=decision.model_dump(mode="json"),
            metadata={"outcome": decision.outcome.value, "harness": True},
        )
        self.context.session.flush()

    def _apply_decision(self, run: RunState, decision: CollectGateDecision) -> RunState:
        latest_run = self.context.runs.require(run.id)
        metadata = {**latest_run.metadata, "last_collect_gate": decision.model_dump(mode="json")}

        if decision.outcome == CollectGateOutcome.ENTER_WRITING:
            next_run = latest_run.model_copy(
                update={
                    "phase": RunPhase.WRITING,
                    "status": RunStatus.RUNNING,
                    "selected_cluster_ids": decision.selected_cluster_ids,
                    "metrics": {**latest_run.metrics, **decision.metrics},
                    "metadata": metadata,
                    "updated_at": utc_now(),
                }
            )
            self.context.runs.add(next_run)
            self.context.complete_phase(
                run_id=latest_run.id,
                phase=RunPhase.EVALUATION_GATE,
                summary="Collect gate passed; entering writing loop.",
            )
            self.context.session.flush()
            return next_run

        if decision.outcome == CollectGateOutcome.FOLLOWUP_NOW:
            counters = latest_run.loop_counters.model_copy(
                update={"followup_rounds": latest_run.loop_counters.followup_rounds + 1}
            )
            next_run = latest_run.model_copy(
                update={
                    "phase": RunPhase.FOLLOWUP,
                    "loop_counters": counters,
                    "metrics": {**latest_run.metrics, **decision.metrics},
                    "metadata": metadata,
                    "updated_at": utc_now(),
                }
            )
            self.context.runs.add(next_run)
            self.context.complete_phase(
                run_id=latest_run.id,
                phase=RunPhase.FOLLOWUP,
                summary="Collect gate requested follow-up.",
            )
            self.context.session.flush()
            return next_run

        if decision.outcome in {
            CollectGateOutcome.RECLUSTER,
            CollectGateOutcome.CONTINUE_COLLECTING,
        }:
            next_phase = (
                RunPhase.CLUSTERING
                if decision.outcome == CollectGateOutcome.RECLUSTER
                else RunPhase.COLLECT_PLANNING
            )
            next_run = latest_run.model_copy(
                update={
                    "phase": next_phase,
                    "metrics": {**latest_run.metrics, **decision.metrics},
                    "metadata": metadata,
                    "updated_at": utc_now(),
                }
            )
            self.context.runs.add(next_run)
            self.context.session.flush()
            return next_run

        if decision.outcome == CollectGateOutcome.NEEDS_MANUAL_REVIEW:
            next_run = latest_run.model_copy(
                update={
                    "phase": RunPhase.EVALUATION_GATE,
                    "status": RunStatus.PAUSED,
                    "metrics": {**latest_run.metrics, **decision.metrics},
                    "metadata": {**metadata, "manual_review_required": True},
                    "updated_at": utc_now(),
                }
            )
            self.context.runs.add(next_run)
            self.context.session.flush()
            return next_run

        return self.context.fail_run(
            latest_run,
            phase=RunPhase.EVALUATION_GATE,
            error_summary=decision.reasoning_summary,
        )

    def _force_exhausted_decision(self, decision: CollectGateDecision) -> CollectGateDecision:
        if decision.outcome == CollectGateOutcome.ENTER_WRITING:
            return decision
        if self.context.config.manual_review_on_failure:
            return CollectGateDecision(
                outcome=CollectGateOutcome.NEEDS_MANUAL_REVIEW,
                reasoning_summary="Collect budget exhausted before gate passed.",
                risk_flags=["collect_budget_exhausted"],
                metrics=decision.metrics,
                metadata={"previous_outcome": decision.outcome.value},
            )
        return CollectGateDecision(
            outcome=CollectGateOutcome.FAIL,
            reasoning_summary="Collect budget exhausted before gate passed.",
            risk_flags=["collect_budget_exhausted"],
            metrics=decision.metrics,
            metadata={"previous_outcome": decision.outcome.value},
        )

    @staticmethod
    def _tasks_from_run_metadata(run: RunState) -> dict[RunPhase, list[AgentTask]]:
        raw_tasks = run.metadata.get("collect_tasks", {})
        tasks: dict[RunPhase, list[AgentTask]] = {}
        if not isinstance(raw_tasks, dict):
            return tasks
        for phase_value, phase_tasks in raw_tasks.items():
            phase = RunPhase(phase_value)
            tasks[phase] = [AgentTask.model_validate(task) for task in phase_tasks]
        return tasks
