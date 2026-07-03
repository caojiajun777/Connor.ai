"""Clusterer task construction and context shaping."""

from __future__ import annotations

from typing import Any

from app.domain import AgentRole, CandidateItem, EvidenceItem, RunPhase


class ClusterTaskFactory:
    """Create Clusterer tasks and compact candidate context."""

    def create_task(
        self,
        *,
        objective: str,
        context: dict[str, Any] | None = None,
    ):
        from app.harness.decisions import AgentTask

        return AgentTask(
            agent_role=AgentRole.CLUSTERER,
            phase=RunPhase.CLUSTERING,
            task=(
                "Merge related candidate claims into event-level clusters. "
                "Preserve evidence lineage, conflicts, and links between early signals "
                f"and later confirmations. Objective: {objective}"
            ),
            context={
                "cluster_output_contract": (
                    "Return cluster_drafts. Each draft must include candidate_ids, title, "
                    "canonical_claim, category, and enough evidence lineage to audit the merge."
                ),
                **(context or {}),
            },
        )

    @staticmethod
    def candidate_context(
        *,
        candidates: list[CandidateItem],
        evidence: list[EvidenceItem],
    ) -> list[dict[str, Any]]:
        evidence_by_id = {item.id: item for item in evidence}
        return [
            {
                "id": candidate.id,
                "category": candidate.category.value,
                "signal_status": candidate.signal_status.value if candidate.signal_status else None,
                "claim_summary": candidate.claim_summary,
                "entities": candidate.entities,
                "tickers": candidate.tickers,
                "topics": candidate.topics,
                "evidence_ids": candidate.evidence_ids,
                "evidence_titles": [
                    evidence_by_id[evidence_id].title
                    for evidence_id in candidate.evidence_ids
                    if evidence_id in evidence_by_id
                ],
                "uncertainty": candidate.uncertainty.value,
                "evidence_strength": candidate.evidence_strength.value,
                "why_it_matters": candidate.why_it_matters,
                "potential_impact": candidate.potential_impact,
                "metadata": candidate.metadata,
            }
            for candidate in candidates
        ]
