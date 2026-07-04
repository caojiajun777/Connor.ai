"""Evaluator task construction and context shaping."""

from __future__ import annotations

from typing import Any

from app.domain import AgentRole, CandidateItem, EventCluster, EvidenceItem, RunPhase
from app.evaluators.profiles import (
    EVALUATOR_ROLES,
    EvaluatorProfileRegistry,
    create_default_evaluator_profile_registry,
)


class EvaluatorTaskFactory:
    """Create evaluator tasks and compact cluster context."""

    def __init__(self, profile_registry: EvaluatorProfileRegistry | None = None):
        self.profile_registry = profile_registry or create_default_evaluator_profile_registry()

    def create_task(
        self,
        *,
        role: AgentRole,
        objective: str,
        context: dict[str, Any] | None = None,
    ):
        from app.harness.decisions import AgentTask

        if role not in EVALUATOR_ROLES:
            raise ValueError(f"not an evaluator role: {role.value}")
        profile = self.profile_registry.require(role)
        return AgentTask(
            agent_role=role,
            phase=RunPhase.EVALUATING,
            task=(
                "Evaluate eligible event clusters using your evaluator profile. "
                "Return evaluation_drafts only for clusters your profile can judge. "
                "Preserve uncertainty, missing evidence, risk flags, and follow-up points. "
                f"Objective: {objective}"
            ),
            context={
                "evaluator_profile": profile.task_profile(),
                "evaluation_output_contract": (
                    "Return evaluation_drafts. Each draft must include cluster_id, evaluator_type, "
                    "dimension_scores, total_score, decision, reasoning_summary, risk_flags, "
                    "required_followups, and missing_evidence."
                ),
                **(context or {}),
            },
        )

    def create_all_tasks(
        self,
        *,
        objective: str,
        context: dict[str, Any] | None = None,
    ) -> list:
        """Create one task for each default evaluator role."""

        return [
            self.create_task(role=role, objective=objective, context=context)
            for role in (
                AgentRole.FRONTIER_EVALUATOR,
                AgentRole.EVENT_EVALUATOR,
                AgentRole.MARKET_EVALUATOR,
            )
        ]

    @staticmethod
    def cluster_context(
        *,
        clusters: list[EventCluster],
        candidates: list[CandidateItem],
        evidence: list[EvidenceItem],
    ) -> list[dict[str, Any]]:
        """Build compact cluster context for evaluator agents."""

        candidates_by_id = {candidate.id: candidate for candidate in candidates}
        evidence_by_id = {item.id: item for item in evidence}
        return [
            {
                "id": cluster.id,
                "category": cluster.category.value,
                "title": cluster.title,
                "canonical_claim": cluster.canonical_claim,
                "entities": cluster.entities,
                "tickers": cluster.tickers,
                "topics": cluster.topics,
                "candidate_ids": cluster.candidate_ids,
                "candidate_summaries": [
                    candidates_by_id[candidate_id].claim_summary
                    for candidate_id in cluster.candidate_ids
                    if candidate_id in candidates_by_id
                ],
                "evidence_ids": cluster.evidence_ids,
                "evidence_titles": [
                    evidence_by_id[evidence_id].title
                    for evidence_id in cluster.evidence_ids
                    if evidence_id in evidence_by_id
                ],
                "evidence_strengths": [
                    evidence_by_id[evidence_id].strength.value
                    for evidence_id in cluster.evidence_ids
                    if evidence_id in evidence_by_id
                ],
                "timeline": [
                    {
                        "summary": entry.summary,
                        "evidence_ids": entry.evidence_ids,
                        "candidate_ids": entry.candidate_ids,
                    }
                    for entry in cluster.timeline
                ],
                "conflict_summary": cluster.conflict_summary,
                "metadata": cluster.metadata,
            }
            for cluster in clusters
        ]
