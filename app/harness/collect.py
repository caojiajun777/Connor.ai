"""Collect loop harness."""

from __future__ import annotations

import logging
from time import perf_counter
from collections.abc import Mapping

from app.agents import AgentRunRequest, AgentScopeExecutionError
from app.clusterer.materialization import ClusterOutputMaterializer
from app.clusterer.tasks import ClusterTaskFactory
from app.domain import RunPhase, RunState, RunStatus, TraceEventType, TraceStatus
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

logger = logging.getLogger(__name__)


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
            # Followup rounds reuse the same collect round — they do not
            # consume a fresh collect_rounds slot so the two budgets are
            # independent.
            if run.phase == RunPhase.FOLLOWUP:
                run = self._transition_followup_to_collect(run)
            else:
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

    def _transition_followup_to_collect(self, run: RunState) -> RunState:
        """Transition from a followup round into a fresh collect planning phase
        without consuming a collect_rounds slot."""

        self.context.session.flush()
        next_run = run.model_copy(
            update={
                "phase": RunPhase.COLLECT_PLANNING,
                "status": RunStatus.RUNNING,
                "updated_at": utc_now(),
            }
        )
        self.context.runs.add(next_run)
        self.context.trace_service.record_event(
            run_id=run.id,
            phase=RunPhase.COLLECT_PLANNING,
            event_type=TraceEventType.PHASE_STARTED,
            status=TraceStatus.STARTED,
            summary=(
                f"Collect round {run.loop_counters.collect_rounds} resumed "
                f"after followup (followup round {run.loop_counters.followup_rounds})."
            ),
            metadata={
                "collect_round": run.loop_counters.collect_rounds,
                "followup_round": run.loop_counters.followup_rounds,
                "harness": True,
            },
        )
        self.context.checkpoint()
        return next_run

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
        self.context.checkpoint()
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

        if tasks and self.context.agent_runner is None:
            raise HarnessError(f"{phase.value} tasks require an AgentRunner")

        self.context.trace_service.record_event(
            run_id=run.id,
            phase=phase,
            event_type=TraceEventType.PHASE_STARTED,
            status=TraceStatus.STARTED,
            summary=f"{phase.value} phase started with {len(tasks)} task(s).",
            metadata={"task_count": len(tasks), "harness": True},
        )
        self.context.checkpoint()

        if phase == RunPhase.WATCHLIST_UPDATE and self.context.config.expire_due_watchlist_items:
            self.watchlist_lifecycle.expire_due_items(run=run, phase=phase)

        if (
            phase == RunPhase.SCOUTING
            and len(tasks) > 1
            and self.context.config.parallelize_scouts
        ):
            self._execute_scout_tasks_parallel(
                run, phase, tasks, tasks_by_phase=tasks_by_phase
            )
            return

        tool_call_count = 0
        successful_task_count = 0
        for task_index, task in enumerate(tasks, start=1):
            if task.phase != phase:
                raise HarnessError(f"task phase {task.phase.value} does not match {phase.value}")
            started_at = perf_counter()
            task_trace = self._record_task_progress(
                run=run,
                phase=phase,
                task=task,
                task_index=task_index,
                task_count=len(tasks),
                status=TraceStatus.STARTED,
                summary=f"Harness dispatching {task.agent_role.value} task.",
            )
            try:
                result = self.context.agent_runner.run(
                    AgentRunRequest(
                        run_id=run.id,
                        phase=phase,
                        agent_role=task.agent_role,
                        task=task.task,
                        context=self._build_task_context(run, phase, task.context),
                    )
                )
            except AgentScopeExecutionError as exc:
                if not self._can_continue_after_agent_error(phase):
                    raise
                duration_ms = int((perf_counter() - started_at) * 1000)
                skipped_summary = (
                    "Scout task failed; continuing collect."
                    if phase == RunPhase.SCOUTING
                    else "Watchlist task failed; continuing collect."
                )
                self.context.trace_service.record_event(
                    run_id=run.id,
                    phase=phase,
                    agent_role=task.agent_role,
                    event_type=TraceEventType.AGENT_DECISION,
                    status=TraceStatus.FAILED,
                    summary=skipped_summary,
                    error=str(exc) or type(exc).__name__,
                    parent_id=task_trace.id,
                    duration_ms=duration_ms,
                    metadata={
                        "harness": True,
                        "skipped_task": True,
                        "continue_on_agent_error": True,
                        "continue_on_scout_agent_error": phase == RunPhase.SCOUTING,
                        "continue_on_watchlist_agent_error": phase == RunPhase.WATCHLIST_UPDATE,
                        "duration_ms": duration_ms,
                    },
                )
                self.context.checkpoint()
                continue
            tool_call_count += len(result.tool_results)
            successful_task_count += 1
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
            duration_ms = int((perf_counter() - started_at) * 1000)
            self._record_task_progress(
                run=run,
                phase=phase,
                task=task,
                task_index=task_index,
                task_count=len(tasks),
                status=TraceStatus.SUCCEEDED,
                summary=f"Harness completed {task.agent_role.value} task.",
                parent_id=task_trace.id,
                duration_ms=duration_ms,
                metadata={
                    "tool_call_count": len(result.tool_results),
                    "duration_ms": duration_ms,
                },
            )

        if (
            phase == RunPhase.WATCHLIST_UPDATE
            and successful_task_count == 0
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

    def _execute_scout_tasks_parallel(
        self,
        run: RunState,
        _phase: RunPhase,
        tasks: list[AgentTask],
        *,
        tasks_by_phase: Mapping[RunPhase, list[AgentTask]],
    ) -> None:
        """Run scout tasks in parallel using thread-pool isolation.

        Each scout gets its own database session (thread-safe on PostgreSQL).
        Results are materialised sequentially on the main session after all
        scouts complete.  SQLite is detected and falls back to serial execution.
        """

        from concurrent.futures import ThreadPoolExecutor, as_completed

        if self.context.agent_runner is None:
            raise HarnessError("Scout parallelisation requires an AgentRunner")

        materialize = self.context.config.materialize_scout_candidates
        bootstrap = self._should_bootstrap_single_agent(tasks_by_phase)

        # SQLite does not support concurrent writes across threads,
        # even with WAL mode.  Only PostgreSQL can benefit from
        # multi-threaded scout parallelism.  Fall back to serial
        # execution for SQLite (both in-memory and file-based).
        engine_url = str(self.context.session.get_bind().url)
        if "sqlite" in engine_url:
            logger.info("SQLite detected; falling back to serial scout execution.")
            # Re-run via the normal serial path (copy of the loop body below).
            tool_call_count = 0
            successful_task_count = 0
            for task_index, task in enumerate(tasks, start=1):
                if task.phase != _phase:
                    raise HarnessError(
                        f"task phase {task.phase.value} does not match {_phase.value}"
                    )
                try:
                    result = self.context.agent_runner.run(
                        AgentRunRequest(
                            run_id=run.id,
                            phase=_phase,
                            agent_role=task.agent_role,
                            task=task.task,
                            context=self._build_task_context(run, _phase, task.context),
                        )
                    )
                except AgentScopeExecutionError as exc:
                    if not self.context.config.continue_on_scout_agent_error:
                        raise
                    self.context.trace_service.record_event(
                        run_id=run.id,
                        phase=_phase,
                        agent_role=task.agent_role,
                        event_type=TraceEventType.AGENT_DECISION,
                        status=TraceStatus.FAILED,
                        summary="Scout task failed; continuing collect.",
                        error=str(exc) or type(exc).__name__,
                        metadata={"harness": True, "skipped_task": True},
                    )
                    self.context.checkpoint()
                    continue
                tool_call_count += len(result.tool_results)
                successful_task_count += 1
                if materialize:
                    self.materializer.materialize(
                        run=run,
                        phase=_phase,
                        agent_role=task.agent_role,
                        result=result,
                        bootstrap_cluster_and_evaluation=bootstrap,
                    )
            latest_run = self.context.runs.require(run.id)
            counters = latest_run.loop_counters.model_copy(
                update={
                    "tool_calls": latest_run.loop_counters.tool_calls + tool_call_count,
                    "model_calls": latest_run.loop_counters.model_calls + successful_task_count,
                }
            )
            self.context.runs.add(
                latest_run.model_copy(update={"loop_counters": counters})
            )
            self.context.complete_phase(
                run_id=run.id,
                phase=_phase,
                summary=f"{_phase.value} phase completed (serial fallback).",
            )
            return

        # Commit the main session so that the RunState and any
        # previously-persisted data are visible to per-scout thread sessions.
        self.context.session.commit()

        # Capture shared read-only dependencies before entering threads.
        tool_registry = self.context.agent_runner.tool_registry
        role_registry = self.context.agent_runner.role_registry
        model_factory = self.context.agent_runner.model_factory

        # Each scout thread builds its own session + runner from the shared engine.
        from app.db.session import SessionLocal

        def _run_one(task: AgentTask) -> tuple[AgentTask, object | None, str | None]:
            """Returns (task, AgentRunResult | None, error_message | None)."""
            session = SessionLocal()
            try:
                from app.agents import AgentRunner as _AgentRunner
                from app.services import TraceService as _TraceService

                trace_svc = _TraceService(session)
                runner = _AgentRunner(
                    session,
                    role_registry=role_registry,
                    tool_registry=tool_registry,
                    model_factory=model_factory,
                    trace_service=trace_svc,
                )
                result = runner.run(
                    AgentRunRequest(
                        run_id=run.id,
                        phase=_phase,
                        agent_role=task.agent_role,
                        task=task.task,
                        context=self._build_task_context(run, _phase, task.context),
                    )
                )
                session.commit()
                return (task, result, None)
            except AgentScopeExecutionError as exc:
                session.rollback()
                if not self.context.config.continue_on_scout_agent_error:
                    raise
                return (task, None, str(exc) or type(exc).__name__)
            finally:
                session.close()

        results: list[tuple[AgentTask, object | None, str | None]] = []
        with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            futures = {executor.submit(_run_one, task): task for task in tasks}
            for future in as_completed(futures):
                results.append(future.result())

        # Materialise sequentially on the main session.
        tool_call_total = 0
        successful = 0
        for task, result, error in results:
            if error is not None:
                self.context.trace_service.record_event(
                    run_id=run.id,
                    phase=_phase,
                    agent_role=task.agent_role,
                    event_type=TraceEventType.AGENT_DECISION,
                    status=TraceStatus.FAILED,
                    summary="Scout task failed (parallel); continuing collect.",
                    error=error,
                    metadata={"harness": True, "parallel": True, "skipped_task": True},
                )
                self.context.checkpoint()
                continue

            successful += 1
            tool_call_total += len(result.tool_results)  # type: ignore[union-attr]
            if materialize:
                self.materializer.materialize(
                    run=run,
                    phase=_phase,
                    agent_role=task.agent_role,
                    result=result,
                    bootstrap_cluster_and_evaluation=bootstrap,
                )

        # Update run counters.
        latest_run = self.context.runs.require(run.id)
        counters = latest_run.loop_counters.model_copy(
            update={
                "tool_calls": latest_run.loop_counters.tool_calls + tool_call_total,
                "model_calls": latest_run.loop_counters.model_calls + successful,
            }
        )
        self.context.runs.add(latest_run.model_copy(update={"loop_counters": counters}))
        self.context.complete_phase(
            run_id=run.id,
            phase=_phase,
            summary=(
                f"{_phase.value} phase completed (parallel, "
                f"{successful}/{len(tasks)} scouts succeeded)."
            ),
        )

    def _can_continue_after_agent_error(self, phase: RunPhase) -> bool:
        if phase == RunPhase.SCOUTING:
            return self.context.config.continue_on_scout_agent_error
        if phase == RunPhase.WATCHLIST_UPDATE:
            return self.context.config.continue_on_watchlist_agent_error
        return False

    def _record_task_progress(
        self,
        *,
        run: RunState,
        phase: RunPhase,
        task: AgentTask,
        task_index: int,
        task_count: int,
        status: TraceStatus,
        summary: str,
        parent_id: str | None = None,
        duration_ms: int | None = None,
        metadata: dict | None = None,
    ):
        logger.info(
            "Connor collect progress: run=%s phase=%s role=%s task=%s/%s status=%s",
            run.id,
            phase.value,
            task.agent_role.value,
            task_index,
            task_count,
            status.value,
        )
        event = self.context.trace_service.record_event(
            run_id=run.id,
            phase=phase,
            agent_role=task.agent_role,
            event_type=TraceEventType.AGENT_DECISION,
            status=status,
            summary=summary,
            parent_id=parent_id,
            duration_ms=duration_ms,
            metadata={
                "harness": True,
                "task_progress": True,
                "task_index": task_index,
                "task_count": task_count,
                **(metadata or {}),
            },
        )
        self.context.checkpoint()
        return event

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
        self.context.checkpoint()

    def _apply_decision(self, run: RunState, decision: CollectGateDecision) -> RunState:
        latest_run = self.context.runs.require(run.id)
        metadata = {**latest_run.metadata, "last_collect_gate": decision.model_dump(mode="json")}

        if decision.outcome == CollectGateOutcome.ENTER_WRITING:
            self._mark_selected_clusters(decision.selected_cluster_ids)
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
            self.context.checkpoint()
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
            self.context.checkpoint()
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
            self.context.checkpoint()
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
            self.context.checkpoint()
            return next_run

        return self.context.fail_run(
            latest_run,
            phase=RunPhase.EVALUATION_GATE,
            error_summary=decision.reasoning_summary,
        )

    def _mark_selected_clusters(self, cluster_ids: list[str]) -> None:
        for cluster_id in cluster_ids:
            cluster = self.context.runs.clusters.get(cluster_id)
            if cluster is None:
                continue
            if not cluster.selected:
                self.context.runs.clusters.add(
                    cluster.model_copy(update={"selected": True, "updated_at": utc_now()})
                )

    def _force_exhausted_decision(self, decision: CollectGateDecision) -> CollectGateDecision:
        if decision.outcome in {
            CollectGateOutcome.ENTER_WRITING,
            CollectGateOutcome.FOLLOWUP_NOW,
        }:
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
