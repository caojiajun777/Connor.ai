"""Materialize AgentScope agent outputs into Connor domain objects."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agents.outputs import CandidateDraft, ScoutOutput
from app.core.ids import deterministic_id
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
    EvidenceItem,
    EvidenceStrength,
    RunPhase,
    RunState,
    SignalStatus,
    TraceEventType,
)
from app.domain.base import utc_now
from app.harness.context import HarnessContext
from app.harness.exceptions import HarnessError
from app.repositories import CandidateRepository, EvaluationRepository, EventClusterRepository
from app.repositories import EvidenceRepository
from app.scouts.profiles import (
    ScoutProfileError,
    ScoutProfileRegistry,
    create_default_scout_profile_registry,
)


FINANCE_SIGNAL_STATUS_NORMALIZATIONS = {
    SignalStatus.OFFICIAL_CONFIRMATION: SignalStatus.CONFIRMED_FACT,
    SignalStatus.UNCONFIRMED_LEAK: SignalStatus.SINGLE_SOURCE_SIGNAL,
    SignalStatus.GRAY_ROLLOUT_FEEDBACK: SignalStatus.SINGLE_SOURCE_SIGNAL,
    SignalStatus.CODE_ANOMALY: SignalStatus.SINGLE_SOURCE_SIGNAL,
    SignalStatus.RESEARCHER_HINT: SignalStatus.SINGLE_SOURCE_SIGNAL,
    SignalStatus.COMMUNITY_RUMOR: SignalStatus.SINGLE_SOURCE_SIGNAL,
}


@dataclass
class MaterializationResult:
    """Domain objects created from one agent result."""

    candidate_ids: list[str] = field(default_factory=list)
    cluster_ids: list[str] = field(default_factory=list)
    evaluation_ids: list[str] = field(default_factory=list)


class ScoutOutputMaterializer:
    """Persist Scout candidate drafts and optional single-agent bootstrap objects."""

    def __init__(
        self,
        context: HarnessContext,
        *,
        scout_profiles: ScoutProfileRegistry | None = None,
    ):
        self.context = context
        self.candidates = CandidateRepository(context.session)
        self.clusters = EventClusterRepository(context.session)
        self.evaluations = EvaluationRepository(context.session)
        self.evidence = EvidenceRepository(context.session)
        self.scout_profiles = scout_profiles or create_default_scout_profile_registry()

    def materialize(
        self,
        *,
        run: RunState,
        phase: RunPhase,
        agent_role: AgentRole,
        result: AgentRunResult,
        bootstrap_cluster_and_evaluation: bool,
    ) -> MaterializationResult:
        """Materialize ScoutOutput candidate drafts into Connor domain state."""

        if not isinstance(result.structured_output, ScoutOutput):
            return MaterializationResult()
        if not result.structured_output.candidate_drafts:
            return MaterializationResult()

        available_evidence_ids = self._available_evidence_ids(result)
        materialized = MaterializationResult()

        for draft in result.structured_output.candidate_drafts:
            candidate = self._create_candidate(
                run=run,
                agent_role=agent_role,
                draft=draft,
                available_evidence_ids=available_evidence_ids,
            )
            self.candidates.add(candidate)
            materialized.candidate_ids.append(candidate.id)
            self.context.trace_service.object_created(
                run_id=run.id,
                phase=phase,
                agent_role=agent_role,
                event_type=TraceEventType.CANDIDATE_CREATED,
                created_object=candidate,
                summary=f"Scout materialized candidate: {candidate.claim_summary}",
            )

            if bootstrap_cluster_and_evaluation:
                cluster = self._create_bootstrap_cluster(run=run, candidate=candidate)
                self.clusters.add(cluster)
                materialized.cluster_ids.append(cluster.id)
                self.context.trace_service.object_created(
                    run_id=run.id,
                    phase=RunPhase.CLUSTERING,
                    agent_role=AgentRole.CLUSTERER,
                    event_type=TraceEventType.CLUSTER_CREATED,
                    created_object=cluster,
                    summary=f"Single-agent bootstrap cluster created: {cluster.title}",
                )

                evaluation = self._create_bootstrap_evaluation(run=run, candidate=candidate, cluster=cluster)
                self.evaluations.add(evaluation)
                materialized.evaluation_ids.append(evaluation.id)
                self.context.trace_service.object_created(
                    run_id=run.id,
                    phase=RunPhase.EVALUATING,
                    agent_role=evaluation.created_by_agent,
                    event_type=TraceEventType.EVALUATION_CREATED,
                    created_object=evaluation,
                    summary=f"Single-agent bootstrap evaluation created: {evaluation.decision.value}",
                )

        self._update_run_lineage(run.id, materialized)
        self.context.session.flush()
        return materialized

    def _create_candidate(
        self,
        *,
        run: RunState,
        agent_role: AgentRole,
        draft: CandidateDraft,
        available_evidence_ids: list[str],
    ) -> CandidateItem:
        requested_evidence_ids = list(draft.evidence_ids)
        fallback_evidence_ids = list(available_evidence_ids)
        evidence_ids, evidence_items = self._resolve_evidence_ids(requested_evidence_ids)
        if requested_evidence_ids and not evidence_ids:
            evidence_ids, evidence_items = self._resolve_evidence_ids(fallback_evidence_ids)
        elif not requested_evidence_ids:
            evidence_ids, evidence_items = self._resolve_evidence_ids(fallback_evidence_ids)

        metadata = dict(draft.metadata)
        if requested_evidence_ids and set(requested_evidence_ids) != set(evidence_ids):
            metadata["requested_evidence_ids"] = requested_evidence_ids
            metadata["resolved_evidence_ids"] = evidence_ids

        if not evidence_ids:
            # When an agent produces a draft without valid tool-sourced
            # evidence, keep the object auditable by downgrading it to a
            # manual hypothesis instead of persisting invented evidence IDs.
            updates = {
                "signal_status": SignalStatus.MANUAL_HYPOTHESIS,
                "evidence_strength": EvidenceStrength.UNKNOWN,
                "metadata": {
                    **metadata,
                    "normalized_missing_evidence": True,
                },
            }
            if draft.category == CandidateCategory.CONFIRMED_EVENT:
                updates["category"] = CandidateCategory.OFFICIAL_UPDATE
            draft = draft.model_copy(update=updates)
            metadata = dict(draft.metadata)
        draft, metadata = self._normalize_draft_for_profile(
            agent_role=agent_role,
            draft=draft,
            metadata=metadata,
        )
        profile = self.scout_profiles.require(agent_role)
        if profile.required_followup_questions and not draft.followup_questions:
            draft, metadata = self._add_default_followup_question(
                agent_role=agent_role,
                draft=draft,
                metadata=metadata,
            )
        try:
            profile.validate_draft(draft, evidence_items)
        except ScoutProfileError as exc:
            raise HarnessError(str(exc)) from exc

        candidate_id = self._stable_id(
            "cand",
            {
                "run_id": run.id,
                "agent_role": agent_role.value,
                "claim_summary": draft.claim_summary,
                "evidence_ids": evidence_ids,
            },
        )
        return CandidateItem(
            id=candidate_id,
            run_id=run.id,
            category=draft.category,
            signal_status=draft.signal_status,
            claim_summary=draft.claim_summary,
            entities=draft.entities,
            tickers=draft.tickers,
            topics=draft.topics,
            evidence_ids=evidence_ids,
            uncertainty=draft.uncertainty,
            evidence_strength=draft.evidence_strength,
            why_it_matters=draft.why_it_matters,
            potential_impact=draft.potential_impact,
            followup_questions=draft.followup_questions,
            created_by_agent=agent_role,
            metadata={
                **metadata,
                "materialized_by": "ScoutOutputMaterializer",
                "scout_profile": profile.role.value,
            },
            created_at=utc_now(),
        )

    @staticmethod
    def _normalize_draft_for_profile(
        *,
        agent_role: AgentRole,
        draft: CandidateDraft,
        metadata: dict,
    ) -> tuple[CandidateDraft, dict]:
        """Normalize common LLM category slips that are still role-valid."""

        if agent_role == AgentRole.FINANCE_SCOUT:
            next_metadata = dict(metadata)
            updates = {}
            if draft.category != CandidateCategory.TECH_FINANCE:
                next_metadata = {
                    **next_metadata,
                    "normalized_category_from": draft.category.value,
                    "normalized_category_reason": "finance_scout_outputs_tech_finance",
                }
                updates["category"] = CandidateCategory.TECH_FINANCE

            normalized_signal_status = FINANCE_SIGNAL_STATUS_NORMALIZATIONS.get(
                draft.signal_status
            )
            if normalized_signal_status is not None:
                next_metadata = {
                    **next_metadata,
                    "normalized_signal_status_from": draft.signal_status.value,
                    "normalized_signal_status_reason": "finance_scout_status_boundary",
                }
                updates["signal_status"] = normalized_signal_status

            if updates:
                updates["metadata"] = next_metadata
                next_draft = draft.model_copy(update=updates)
                return next_draft, next_metadata

        if (
            agent_role == AgentRole.OFFICIAL_SCOUT
            and draft.category
            not in {
                CandidateCategory.CONFIRMED_EVENT,
                CandidateCategory.OFFICIAL_UPDATE,
            }
        ):
            next_metadata = {
                **metadata,
                "normalized_category_from": draft.category.value,
                "normalized_category_reason": "official_scout_outputs_official_update",
            }
            next_draft = draft.model_copy(
                update={
                    "category": CandidateCategory.OFFICIAL_UPDATE,
                    "metadata": next_metadata,
                }
            )
            return next_draft, next_metadata

        return draft, metadata

    @staticmethod
    def _add_default_followup_question(
        *,
        agent_role: AgentRole,
        draft: CandidateDraft,
        metadata: dict,
    ) -> tuple[CandidateDraft, dict]:
        followup_by_role = {
            AgentRole.SOCIAL_SCOUT: (
                "Seek independent corroboration and monitor whether the discussion "
                "turns into an official or code-visible signal."
            ),
            AgentRole.CODE_MODEL_SCOUT: (
                "Monitor related repositories, model pages, package metadata, and "
                "release notes for confirming changes."
            ),
            AgentRole.RESEARCH_SCOUT: (
                "Track paper revisions, code release, benchmark replication, and "
                "follow-on discussion from the authors or venue."
            ),
            AgentRole.OFFICIAL_SCOUT: (
                "Track rollout scope, documentation updates, pricing or limit changes, "
                "SDK support, and downstream product adoption."
            ),
            AgentRole.FINANCE_SCOUT: (
                "Track the next filing, earnings commentary, supplier signal, and "
                "ticker-level impact chain."
            ),
        }
        next_metadata = {
            **metadata,
            "normalized_missing_followup_questions": True,
        }
        next_draft = draft.model_copy(
            update={
                "followup_questions": [followup_by_role.get(agent_role, "Track follow-up evidence.")],
                "metadata": next_metadata,
            }
        )
        return next_draft, next_metadata

    def _create_bootstrap_cluster(self, *, run: RunState, candidate: CandidateItem) -> EventCluster:
        cluster_id = self._stable_id(
            "cl",
            {
                "run_id": run.id,
                "candidate_id": candidate.id,
                "claim_summary": candidate.claim_summary,
            },
        )
        return EventCluster(
            id=cluster_id,
            run_id=run.id,
            category=candidate.category,
            title=self._title_from_claim(candidate.claim_summary),
            canonical_claim=candidate.claim_summary,
            candidate_ids=[candidate.id],
            evidence_ids=candidate.evidence_ids,
            entities=candidate.entities,
            tickers=candidate.tickers,
            topics=candidate.topics,
            timeline=[
                ClusterTimelineEntry(
                    observed_at=utc_now(),
                    summary="Single-agent bootstrap cluster created from Scout candidate.",
                    evidence_ids=candidate.evidence_ids,
                    candidate_ids=[candidate.id],
                )
            ],
            dedupe_key=f"single-agent:{candidate.id}",
            selected=False,
            metadata={"bootstrap_single_agent": True},
            created_at=utc_now(),
        )

    def _create_bootstrap_evaluation(
        self,
        *,
        run: RunState,
        candidate: CandidateItem,
        cluster: EventCluster,
    ) -> EvaluationResult:
        evaluator_type, evaluator_role, decision = self._evaluation_policy(candidate)
        required_followups = candidate.followup_questions
        if decision == EvaluationDecision.SELECT_EARLY_SIGNAL and not required_followups:
            required_followups = ["Track for official confirmation or independent corroboration."]

        return EvaluationResult(
            id=self._stable_id(
                "eval",
                {
                    "run_id": run.id,
                    "cluster_id": cluster.id,
                    "candidate_id": candidate.id,
                    "decision": decision.value,
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
                "Single-agent bootstrap evaluation selected this Scout candidate "
                "so the harness can close one traceable collect loop."
            ),
            required_followups=required_followups,
            metadata={"bootstrap_single_agent": True},
            created_at=utc_now(),
        )

    @staticmethod
    def _evaluation_policy(
        candidate: CandidateItem,
    ) -> tuple[EvaluationType, AgentRole, EvaluationDecision]:
        if candidate.category == CandidateCategory.TECH_FINANCE:
            return (
                EvaluationType.MARKET,
                AgentRole.MARKET_EVALUATOR,
                EvaluationDecision.SELECT_CONFIRMED,
            )
        if candidate.category in {
            CandidateCategory.CONFIRMED_EVENT,
            CandidateCategory.OFFICIAL_UPDATE,
        }:
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

    def _update_run_lineage(self, run_id: str, materialized: MaterializationResult) -> None:
        run = self.context.runs.require(run_id)
        existing_meta = run.metadata.get("single_agent_materialization", {})
        updated = run.model_copy(
            update={
                "candidate_ids": self._dedupe(run.candidate_ids + materialized.candidate_ids),
                "cluster_ids": self._dedupe(run.cluster_ids + materialized.cluster_ids),
                "metadata": {
                    **run.metadata,
                    "single_agent_materialization": {
                        "candidate_ids": self._dedupe(
                            existing_meta.get("candidate_ids", []) + materialized.candidate_ids
                        ),
                        "cluster_ids": self._dedupe(
                            existing_meta.get("cluster_ids", []) + materialized.cluster_ids
                        ),
                        "evaluation_ids": self._dedupe(
                            existing_meta.get("evaluation_ids", []) + materialized.evaluation_ids
                        ),
                    },
                },
            }
        )
        self.context.persist_run(updated)

    @staticmethod
    def _available_evidence_ids(result: AgentRunResult) -> list[str]:
        evidence_ids = list(result.structured_output.evidence_ids)
        for tool_result in result.tool_results:
            evidence_ids.extend(item.id for item in tool_result.evidence_items)
        return ScoutOutputMaterializer._dedupe(evidence_ids)

    def _resolve_evidence_ids(self, evidence_ids: list[str]) -> tuple[list[str], list[EvidenceItem]]:
        evidence_items: list[EvidenceItem] = []
        valid_evidence_ids: list[str] = []
        for evidence_id in self._dedupe(evidence_ids):
            item = self.evidence.get(evidence_id)
            if item is not None:
                evidence_items.append(item)
                valid_evidence_ids.append(evidence_id)
            else:
                import logging
                _logger = logging.getLogger(__name__)
                _logger.warning(
                    "Agent produced evidence ID not found in repository: %s", evidence_id
                )
        return valid_evidence_ids, evidence_items

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
    def _title_from_claim(claim: str) -> str:
        title = claim.strip()
        if len(title) <= 96:
            return title
        return title[:93].rstrip() + "..."
