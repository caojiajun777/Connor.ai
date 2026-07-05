"""Materialize Evaluator outputs into EvaluationResult records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy.orm import Session

from app.agents.outputs import EvaluationDraft, EvaluatorOutput
from app.agents.schemas import AgentRunResult
from app.core.ids import IdPrefix, deterministic_id
from app.domain import (
    AgentRole,
    EvaluationDecision,
    EvaluationResult,
    EventCluster,
    RunPhase,
    RunState,
    TraceEventType,
    TraceStatus,
)
from app.domain.base import utc_now
from app.evaluators.profiles import (
    EVALUATOR_ROLES,
    EvaluatorProfileRegistry,
    create_default_evaluator_profile_registry,
)
from app.exceptions import HarnessError
from app.repositories import EvaluationRepository, EventClusterRepository, RunRepository
from app.services import TraceService


class EvaluationMaterializationContext(Protocol):
    """Context interface required by EvaluatorOutputMaterializer."""

    session: Session
    trace_service: TraceService
    runs: RunRepository

    def persist_run(self, run: RunState) -> RunState:
        """Persist an updated RunState."""


@dataclass
class EvaluationMaterializationResult:
    """Domain objects created from one Evaluator result."""

    evaluation_ids: list[str] = field(default_factory=list)
    selected_cluster_ids: list[str] = field(default_factory=list)


class EvaluatorOutputMaterializer:
    """Persist EvaluatorOutput evaluation drafts into Connor domain state."""

    def __init__(
        self,
        context: EvaluationMaterializationContext,
        *,
        profile_registry: EvaluatorProfileRegistry | None = None,
    ):
        self.context = context
        self.profile_registry = profile_registry or create_default_evaluator_profile_registry()
        self.clusters = EventClusterRepository(context.session)
        self.evaluations = EvaluationRepository(context.session)

    def materialize(
        self,
        *,
        run: RunState,
        phase: RunPhase,
        agent_role: AgentRole,
        result: AgentRunResult,
    ) -> EvaluationMaterializationResult:
        """Materialize EvaluatorOutput drafts into persisted evaluations."""

        self.context.session.flush()
        if phase != RunPhase.EVALUATING:
            raise HarnessError(f"evaluation materialization requires evaluating phase, got {phase.value}")
        if agent_role not in EVALUATOR_ROLES:
            raise HarnessError(
                f"evaluation materialization requires evaluator role, got {agent_role.value}"
            )
        if not isinstance(result.structured_output, EvaluatorOutput):
            return EvaluationMaterializationResult()
        if not result.structured_output.evaluation_drafts:
            return EvaluationMaterializationResult()

        profile = self.profile_registry.require(agent_role)
        materialized = EvaluationMaterializationResult()
        for draft in result.structured_output.evaluation_drafts:
            cluster = self._cluster_for_run(run.id, draft.cluster_id)
            if cluster.category not in profile.allowed_categories:
                self.context.trace_service.record_event(
                    run_id=run.id,
                    phase=phase,
                    agent_role=agent_role,
                    event_type=TraceEventType.AGENT_DECISION,
                    status=TraceStatus.SKIPPED,
                    summary=(
                        f"{agent_role.value} skipped ineligible cluster "
                        f"{cluster.id} ({cluster.category.value})."
                    ),
                    reasoning_summary=(
                        "Evaluator draft targeted a cluster category outside this "
                        "role profile; another evaluator role owns that category."
                    ),
                    input_payload=draft.model_dump(mode="json"),
                    metadata={
                        "cluster_id": cluster.id,
                        "cluster_category": cluster.category.value,
                        "allowed_categories": [
                            category.value for category in profile.allowed_categories
                        ],
                        "materialized_by": "EvaluatorOutputMaterializer",
                        "skip_reason": "ineligible_cluster_category",
                    },
                )
                continue
            draft = self._normalize_score_scale(draft)
            draft = self._normalize_decision_for_score(draft)
            try:
                profile.validate_draft(draft, cluster)
                evaluation = self._create_evaluation(
                    run=run,
                    cluster=cluster,
                    draft=draft,
                    agent_role=agent_role,
                )
            except ValueError as exc:
                raise HarnessError(str(exc)) from exc

            self.evaluations.add(evaluation)
            materialized.evaluation_ids.append(evaluation.id)
            if evaluation.decision in {
                EvaluationDecision.SELECT_CONFIRMED,
                EvaluationDecision.SELECT_EARLY_SIGNAL,
            }:
                materialized.selected_cluster_ids.append(cluster.id)
                self.clusters.add(cluster.model_copy(update={"selected": True, "updated_at": utc_now()}))

            self.context.trace_service.record_event(
                run_id=run.id,
                phase=phase,
                agent_role=agent_role,
                event_type=TraceEventType.EVALUATION_CREATED,
                status=TraceStatus.SUCCEEDED,
                summary=f"{agent_role.value} materialized evaluation: {evaluation.decision.value}",
                reasoning_summary=evaluation.reasoning_summary,
                created_objects=[evaluation],
                output_payload=evaluation.model_dump(mode="json"),
                metadata={
                    "cluster_id": cluster.id,
                    "decision": evaluation.decision.value,
                    "evaluator_type": evaluation.evaluator_type.value,
                    "materialized_by": "EvaluatorOutputMaterializer",
                },
            )

        self._update_run_metadata(run.id, agent_role, materialized)
        self.context.session.flush()
        return materialized

    @staticmethod
    def _normalize_score_scale(draft: EvaluationDraft) -> EvaluationDraft:
        """Normalize common 0-100 or summed score slips into the 0-10 scale."""

        metadata = dict(draft.metadata)
        dimension_scores = dict(draft.dimension_scores)
        normalized_dimensions: dict[str, float] = {}
        original_dimensions: dict[str, float] = {}
        for name, score in dimension_scores.items():
            if 10 < score <= 100:
                original_dimensions[name] = score
                normalized_dimensions[name] = round(score / 10, 2)
            else:
                normalized_dimensions[name] = score

        total_score = draft.total_score
        if original_dimensions:
            metadata["normalized_dimension_scores_from"] = original_dimensions

        if total_score > 10 and normalized_dimensions:
            metadata["normalized_total_score_from"] = total_score
            total_score = round(sum(normalized_dimensions.values()) / len(normalized_dimensions), 2)
        elif 10 < total_score <= 100:
            metadata["normalized_total_score_from"] = total_score
            total_score = round(total_score / 10, 2)

        if metadata != draft.metadata or normalized_dimensions != dimension_scores:
            return draft.model_copy(
                update={
                    "dimension_scores": normalized_dimensions,
                    "total_score": total_score,
                    "metadata": metadata,
                }
            )
        return draft

    @staticmethod
    def _normalize_decision_for_score(draft: EvaluationDraft) -> EvaluationDraft:
        """Downgrade contradictory confirmed selections to follow-up."""

        if draft.decision == EvaluationDecision.SELECT_CONFIRMED:
            reasons = []
            if draft.total_score < 6:
                reasons.append("below_score_threshold")
            if draft.missing_evidence:
                reasons.append("missing_evidence")
            if not reasons:
                return draft
            metadata = {
                **draft.metadata,
                "normalized_decision_from": draft.decision.value,
                "normalized_decision_reason": "select_confirmed_" + "_and_".join(reasons),
            }
            required_followups = list(draft.required_followups) or list(draft.missing_evidence) or [
                "Resolve the low evaluation score before selecting this cluster as confirmed."
            ]
            return draft.model_copy(
                update={
                    "decision": EvaluationDecision.FOLLOWUP_NOW,
                    "required_followups": required_followups,
                    "metadata": metadata,
                }
            )
        return draft

    def _cluster_for_run(self, run_id: str, cluster_id: str) -> EventCluster:
        try:
            cluster = self.clusters.require(cluster_id)
        except LookupError as exc:
            raise HarnessError(str(exc)) from exc
        if cluster.run_id != run_id:
            raise HarnessError(f"cluster {cluster_id} does not belong to run {run_id}")
        return cluster

    @staticmethod
    def _create_evaluation(
        *,
        run: RunState,
        cluster: EventCluster,
        draft: EvaluationDraft,
        agent_role: AgentRole,
    ) -> EvaluationResult:
        return EvaluationResult(
            id=deterministic_id(
                IdPrefix.EVALUATION,
                {
                    "run_id": run.id,
                    "cluster_id": cluster.id,
                    "agent_role": agent_role.value,
                    "evaluator_type": draft.evaluator_type.value,
                    "decision": draft.decision.value,
                },
            ),
            run_id=run.id,
            cluster_id=cluster.id,
            evaluator_type=draft.evaluator_type,
            created_by_agent=agent_role,
            dimension_scores=draft.dimension_scores,
            total_score=draft.total_score,
            decision=draft.decision,
            reasoning_summary=draft.reasoning_summary,
            risk_flags=draft.risk_flags,
            required_followups=draft.required_followups,
            missing_evidence=draft.missing_evidence,
            metadata={
                **draft.metadata,
                "materialized_by": "EvaluatorOutputMaterializer",
                "cluster_category": cluster.category.value,
            },
            created_at=utc_now(),
        )

    def _update_run_metadata(
        self,
        run_id: str,
        agent_role: AgentRole,
        materialized: EvaluationMaterializationResult,
    ) -> None:
        run = self.context.runs.require(run_id)
        previous = run.metadata.get("evaluator_materialization", [])
        if not isinstance(previous, list):
            previous = [previous]
        updated_entry = {
            "agent_role": agent_role.value,
            "evaluation_ids": materialized.evaluation_ids,
            "selected_cluster_ids": self._dedupe(materialized.selected_cluster_ids),
        }
        updated = run.model_copy(
            update={
                "metadata": {
                    **run.metadata,
                    "evaluator_materialization": [*previous, updated_entry],
                },
            }
        )
        self.context.persist_run(updated)

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        deduped: list[str] = []
        for value in values:
            if value not in deduped:
                deduped.append(value)
        return deduped
