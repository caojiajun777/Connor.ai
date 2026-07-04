"""Watchlist Agent task construction and context shaping."""

from __future__ import annotations

from typing import Any

from app.domain import (
    AgentRole,
    ArchivedSignal,
    CandidateItem,
    EvaluationResult,
    EventCluster,
    EvidenceItem,
    IntelligenceThread,
    RunPhase,
    WatchlistItem,
)


def watchlist_prompt_extension() -> str:
    """Return Watchlist Agent role guidance for AgentScope prompts."""

    return (
        "Watchlist memory profile:\n"
        "- Create active watch items only when a signal has a clear follow-up path.\n"
        "- Prefer short TTLs for leaks, gray rollouts, and early frontier signals.\n"
        "- Archive stale, superseded, disproven, low-value, or no-new-signal items instead of deleting them.\n"
        "- Maintain intelligence threads that connect early signals, watch updates, archives, and later outcomes.\n"
        "- Return watchlist_drafts, archive_drafts, and thread_drafts; store only reasoning summaries."
    )


class WatchlistTaskFactory:
    """Create Watchlist Agent tasks and compact memory context."""

    def create_task(
        self,
        *,
        objective: str,
        context: dict[str, Any] | None = None,
    ):
        from app.harness.decisions import AgentTask

        return AgentTask(
            agent_role=AgentRole.WATCHLIST_AGENT,
            phase=RunPhase.WATCHLIST_UPDATE,
            task=(
                "Maintain cost-aware memory for evaluator decisions. Create short-term "
                "watch items, archive inactive signals, and update intelligence threads. "
                f"Objective: {objective}"
            ),
            context={
                "watchlist_output_contract": (
                    "Return watchlist_drafts, archive_drafts, and/or thread_drafts. "
                    "Watchlist drafts need topic, thesis, tier, reactivation_rules, and "
                    "lineage. Archive drafts need original_cluster_id or original_watchlist_id. "
                    "Thread drafts need at least one timeline entry."
                ),
                "ttl_policy": {
                    "short": "3-7 days",
                    "event": "7-21 days",
                    "strategic": "30-90 days",
                },
                **(context or {}),
            },
        )

    @staticmethod
    def memory_context(
        *,
        evaluations: list[EvaluationResult],
        clusters: list[EventCluster],
        candidates: list[CandidateItem],
        evidence: list[EvidenceItem],
        watchlist: list[WatchlistItem],
        archives: list[ArchivedSignal],
        threads: list[IntelligenceThread],
    ) -> dict[str, list[dict[str, Any]]]:
        """Build compact memory context for the Watchlist Agent."""

        clusters_by_id = {cluster.id: cluster for cluster in clusters}
        candidates_by_id = {candidate.id: candidate for candidate in candidates}
        evidence_by_id = {item.id: item for item in evidence}
        return {
            "evaluations": [
                {
                    "id": evaluation.id,
                    "cluster_id": evaluation.cluster_id,
                    "cluster_title": clusters_by_id[evaluation.cluster_id].title
                    if evaluation.cluster_id in clusters_by_id
                    else None,
                    "cluster_category": clusters_by_id[evaluation.cluster_id].category.value
                    if evaluation.cluster_id in clusters_by_id
                    else None,
                    "decision": evaluation.decision.value,
                    "evaluator_type": evaluation.evaluator_type.value,
                    "total_score": evaluation.total_score,
                    "required_followups": evaluation.required_followups,
                    "missing_evidence": evaluation.missing_evidence,
                    "risk_flags": evaluation.risk_flags,
                    "reasoning_summary": evaluation.reasoning_summary,
                }
                for evaluation in evaluations
            ],
            "clusters": [
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
                    "conflict_summary": cluster.conflict_summary,
                    "selected": cluster.selected,
                }
                for cluster in clusters
            ],
            "watchlist": [
                {
                    "id": item.id,
                    "topic": item.topic,
                    "status": item.status.value,
                    "tier": item.watch_tier.value,
                    "priority": item.priority.value,
                    "watch_until": item.watch_until.isoformat(),
                    "last_signal_at": item.last_signal_at.isoformat()
                    if item.last_signal_at
                    else None,
                    "thread_id": item.thread_id,
                    "cluster_ids": item.cluster_ids,
                    "open_questions": item.open_questions,
                }
                for item in watchlist
            ],
            "archives": [
                {
                    "id": archive.id,
                    "original_cluster_id": archive.original_cluster_id,
                    "original_watchlist_id": archive.original_watchlist_id,
                    "archive_reason": archive.archive_reason.value,
                    "final_state": archive.final_state,
                    "thread_id": archive.thread_id,
                }
                for archive in archives
            ],
            "threads": [
                {
                    "id": thread.id,
                    "title": thread.title,
                    "status": thread.status.value,
                    "importance": thread.importance.value,
                    "current_thesis": thread.current_thesis,
                    "open_questions": thread.open_questions,
                    "linked_cluster_ids": thread.linked_cluster_ids,
                    "linked_watchlist_ids": thread.linked_watchlist_ids,
                    "linked_archive_ids": thread.linked_archive_ids,
                }
                for thread in threads
            ],
        }
