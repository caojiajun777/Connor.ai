"""Materialize Clusterer outputs into EventCluster records."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from app.agents.outputs import ClusterDraft, ClustererOutput
from app.core.ids import deterministic_id
from app.exceptions import HarnessError
from app.agents.schemas import AgentRunResult
from app.domain import (
    AgentRole,
    CandidateCategory,
    CandidateItem,
    ClusterTimelineEntry,
    EvaluationDecision,
    EvaluationResult,
    EvaluationType,
    EventCluster,
    RunPhase,
    RunState,
    TraceEventType,
)
from app.domain.base import utc_now
from app.services import TraceService
from sqlalchemy.orm import Session
from app.repositories import (
    CandidateRepository,
    EvaluationRepository,
    EventClusterRepository,
    EvidenceRepository,
    RunRepository,
)


CONFIRMED_CATEGORIES = {
    CandidateCategory.CONFIRMED_EVENT,
    CandidateCategory.OFFICIAL_UPDATE,
}


class ClusterMaterializationContext(Protocol):
    """Context interface required by ClusterOutputMaterializer."""

    session: Session
    trace_service: TraceService
    runs: RunRepository

    def persist_run(self, run: RunState) -> RunState:
        """Persist an updated RunState."""


@dataclass
class ClusterMaterializationResult:
    """Domain objects created from one Clusterer result."""

    cluster_ids: list[str] = field(default_factory=list)
    evaluation_ids: list[str] = field(default_factory=list)


class ClusterOutputMaterializer:
    """Persist Clusterer cluster drafts and optional evaluator bootstrap records."""

    def __init__(self, context: ClusterMaterializationContext):
        self.context = context
        self.candidates = CandidateRepository(context.session)
        self.evidence = EvidenceRepository(context.session)
        self.clusters = EventClusterRepository(context.session)
        self.evaluations = EvaluationRepository(context.session)

    def materialize(
        self,
        *,
        run: RunState,
        phase: RunPhase,
        agent_role: AgentRole,
        result: AgentRunResult,
        bootstrap_evaluations: bool,
    ) -> ClusterMaterializationResult:
        """Materialize ClustererOutput cluster drafts into Connor domain state."""

        self.context.session.flush()
        if agent_role != AgentRole.CLUSTERER:
            raise HarnessError(
                f"cluster materialization requires clusterer role, got {agent_role.value}"
            )
        if not isinstance(result.structured_output, ClustererOutput):
            return ClusterMaterializationResult()
        if not result.structured_output.cluster_drafts:
            return ClusterMaterializationResult()

        materialized = ClusterMaterializationResult()
        for draft in result.structured_output.cluster_drafts:
            cluster = self._create_or_merge_cluster(run=run, draft=draft)
            self.clusters.add(cluster)
            materialized.cluster_ids.append(cluster.id)
            self.context.trace_service.object_created(
                run_id=run.id,
                phase=phase,
                agent_role=AgentRole.CLUSTERER,
                event_type=TraceEventType.CLUSTER_CREATED,
                created_object=cluster,
                summary=f"Clusterer materialized cluster: {cluster.title}",
            )

            if bootstrap_evaluations:
                evaluation = self._create_bootstrap_evaluation(run=run, cluster=cluster)
                self.evaluations.add(evaluation)
                materialized.evaluation_ids.append(evaluation.id)
                self.context.trace_service.object_created(
                    run_id=run.id,
                    phase=RunPhase.EVALUATING,
                    agent_role=evaluation.created_by_agent,
                    event_type=TraceEventType.EVALUATION_CREATED,
                    created_object=evaluation,
                    summary=f"Clusterer bootstrap evaluation created: {evaluation.decision.value}",
                )

        self._update_run_lineage(run.id, materialized)
        self.context.session.flush()
        return materialized

    def _create_or_merge_cluster(self, *, run: RunState, draft: ClusterDraft) -> EventCluster:
        candidates = self._candidate_map(run.id, draft.candidate_ids)
        evidence_ids = self._evidence_ids(draft, candidates)
        for evidence_id in evidence_ids:
            self.evidence.require(evidence_id)

        dedupe_key = draft.dedupe_key or self._dedupe_key(draft, candidates)
        existing = self.clusters.get_by_dedupe_key(dedupe_key)
        metadata = {
            **draft.metadata,
            "materialized_by": "ClusterOutputMaterializer",
            "clusterer_version": "phase9",
            **self._link_metadata(candidates),
        }

        if existing is not None and existing.run_id == run.id:
            timeline = existing.timeline + self._timeline_entries(draft, evidence_ids)
            return existing.model_copy(
                update={
                    "category": draft.category,
                    "title": draft.title,
                    "canonical_claim": draft.canonical_claim,
                    "candidate_ids": self._dedupe(existing.candidate_ids + draft.candidate_ids),
                    "evidence_ids": self._dedupe(existing.evidence_ids + evidence_ids),
                    "entities": self._dedupe(existing.entities + draft.entities + self._candidate_values(candidates, "entities")),
                    "tickers": self._dedupe(existing.tickers + draft.tickers + self._candidate_values(candidates, "tickers")),
                    "topics": self._dedupe(existing.topics + draft.topics + self._candidate_values(candidates, "topics")),
                    "timeline": timeline,
                    "conflict_summary": draft.conflict_summary or existing.conflict_summary,
                    "metadata": {**existing.metadata, **metadata, "merged_existing_cluster": True},
                    "updated_at": utc_now(),
                }
            )

        cluster_id = self._stable_id(
            "cl",
            {
                "run_id": run.id,
                "dedupe_key": dedupe_key,
                "candidate_ids": sorted(draft.candidate_ids),
            },
        )
        return EventCluster(
            id=cluster_id,
            run_id=run.id,
            category=draft.category,
            title=draft.title,
            canonical_claim=draft.canonical_claim,
            candidate_ids=draft.candidate_ids,
            evidence_ids=evidence_ids,
            entities=self._dedupe(draft.entities + self._candidate_values(candidates, "entities")),
            tickers=self._dedupe(draft.tickers + self._candidate_values(candidates, "tickers")),
            topics=self._dedupe(draft.topics + self._candidate_values(candidates, "topics")),
            timeline=self._timeline_entries(draft, evidence_ids),
            conflict_summary=draft.conflict_summary,
            dedupe_key=dedupe_key,
            selected=False,
            metadata=metadata,
            created_at=utc_now(),
        )

    def _candidate_map(self, run_id: str, candidate_ids: list[str]) -> dict[str, CandidateItem]:
        candidates: dict[str, CandidateItem] = {}
        for candidate_id in candidate_ids:
            try:
                candidate = self.candidates.require(candidate_id)
            except LookupError as exc:
                raise HarnessError(str(exc)) from exc
            if candidate.run_id != run_id:
                raise HarnessError(f"candidate {candidate_id} does not belong to run {run_id}")
            candidates[candidate_id] = candidate
        return candidates

    @staticmethod
    def _evidence_ids(draft: ClusterDraft, candidates: dict[str, CandidateItem]) -> list[str]:
        evidence_ids = list(draft.evidence_ids)
        if not evidence_ids:
            for candidate in candidates.values():
                evidence_ids.extend(candidate.evidence_ids)
        else:
            for candidate in candidates.values():
                evidence_ids.extend(candidate.evidence_ids)
        evidence_ids = ClusterOutputMaterializer._dedupe(evidence_ids)
        if not evidence_ids:
            raise HarnessError("cluster drafts require evidence_ids or candidate evidence")
        return evidence_ids

    def _timeline_entries(
        self,
        draft: ClusterDraft,
        evidence_ids: list[str],
    ) -> list[ClusterTimelineEntry]:
        if draft.timeline:
            return [
                ClusterTimelineEntry(
                    observed_at=utc_now(),
                    summary=entry.summary,
                    evidence_ids=entry.evidence_ids or evidence_ids,
                    candidate_ids=entry.candidate_ids or draft.candidate_ids,
                )
                for entry in draft.timeline
            ]
        return [
            ClusterTimelineEntry(
                observed_at=utc_now(),
                summary="Clusterer linked candidate claims into one event cluster.",
                evidence_ids=evidence_ids,
                candidate_ids=draft.candidate_ids,
            )
        ]

    @staticmethod
    def _candidate_values(candidates: dict[str, CandidateItem], field_name: str) -> list[str]:
        values: list[str] = []
        for candidate in candidates.values():
            values.extend(getattr(candidate, field_name))
        return values

    @staticmethod
    def _link_metadata(candidates: dict[str, CandidateItem]) -> dict[str, object]:
        early_signal_ids = [
            candidate.id
            for candidate in candidates.values()
            if candidate.category == CandidateCategory.EARLY_SIGNAL
        ]
        confirmation_ids = [
            candidate.id
            for candidate in candidates.values()
            if candidate.category in CONFIRMED_CATEGORIES
        ]
        metadata: dict[str, object] = {}
        if early_signal_ids and confirmation_ids:
            metadata["confirmed_prior_signal_candidate_ids"] = early_signal_ids
            metadata["confirmation_candidate_ids"] = confirmation_ids
            metadata["confirmation_linked"] = True
        conflict_candidate_ids = ClusterOutputMaterializer._dedupe(
            [
                conflict_id
                for candidate in candidates.values()
                for conflict_id in candidate.metadata.get("conflicts_with_candidate_ids", [])
            ]
        )
        if conflict_candidate_ids:
            metadata["conflict_candidate_ids"] = conflict_candidate_ids
        return metadata

    @staticmethod
    def _dedupe_key(draft: ClusterDraft, candidates: dict[str, CandidateItem]) -> str:
        entities = draft.entities or ClusterOutputMaterializer._candidate_values(candidates, "entities")
        tickers = draft.tickers or ClusterOutputMaterializer._candidate_values(candidates, "tickers")
        topics = draft.topics or ClusterOutputMaterializer._candidate_values(candidates, "topics")
        basis = {
            "category": draft.category.value,
            "entities": sorted(ClusterOutputMaterializer._dedupe([item.lower() for item in entities])),
            "tickers": sorted(ClusterOutputMaterializer._dedupe([item.lower() for item in tickers])),
            "topics": sorted(ClusterOutputMaterializer._dedupe([item.lower() for item in topics]))[:4],
            "claim": ClusterOutputMaterializer._slug(draft.canonical_claim)[:80],
        }
        return deterministic_id(draft.category.value, basis)

    def _create_bootstrap_evaluation(self, *, run: RunState, cluster: EventCluster) -> EvaluationResult:
        evaluator_type, evaluator_role, decision = self._evaluation_policy(cluster)
        required_followups = []
        if decision == EvaluationDecision.SELECT_EARLY_SIGNAL:
            required_followups = [
                "Track the cluster for official confirmation, conflicting evidence, or independent corroboration."
            ]
        return EvaluationResult(
            id=self._stable_id(
                "eval",
                {
                    "run_id": run.id,
                    "cluster_id": cluster.id,
                    "decision": decision.value,
                    "bootstrap": "clusterer",
                },
            ),
            run_id=run.id,
            cluster_id=cluster.id,
            evaluator_type=evaluator_type,
            created_by_agent=evaluator_role,
            dimension_scores={
                "specificity": 7,
                "relevance": 7,
                "impact": 7,
                "trackability": 7,
            },
            total_score=7.0,
            decision=decision,
            reasoning_summary=(
                "Clusterer bootstrap evaluation selected this materialized cluster "
                "until the Phase 10 evaluator group replaces this temporary path."
            ),
            required_followups=required_followups,
            metadata={"bootstrap_clusterer_evaluation": True},
            created_at=utc_now(),
        )

    @staticmethod
    def _evaluation_policy(
        cluster: EventCluster,
    ) -> tuple[EvaluationType, AgentRole, EvaluationDecision]:
        if cluster.category == CandidateCategory.TECH_FINANCE:
            return (
                EvaluationType.MARKET,
                AgentRole.MARKET_EVALUATOR,
                EvaluationDecision.SELECT_CONFIRMED,
            )
        if cluster.category in CONFIRMED_CATEGORIES:
            return (
                EvaluationType.EVENT,
                AgentRole.EVENT_EVALUATOR,
                EvaluationDecision.SELECT_CONFIRMED,
            )
        return (
            EvaluationType.FRONTIER,
            AgentRole.FRONTIER_EVALUATOR,
            EvaluationDecision.SELECT_EARLY_SIGNAL,
        )

    def _update_run_lineage(self, run_id: str, materialized: ClusterMaterializationResult) -> None:
        run = self.context.runs.require(run_id)
        updated = run.model_copy(
            update={
                "cluster_ids": self._dedupe(run.cluster_ids + materialized.cluster_ids),
                "metadata": {
                    **run.metadata,
                    "clusterer_materialization": {
                        "cluster_ids": materialized.cluster_ids,
                        "evaluation_ids": materialized.evaluation_ids,
                    },
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

    @staticmethod
    def _stable_id(prefix: str, payload: dict) -> str:
        return deterministic_id(prefix, payload)

    @staticmethod
    def _slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
