"""Deterministic watchlist lifecycle policies."""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.outputs import ArchiveDraft, ThreadDraft, ThreadTimelineDraft, WatchlistDraft
from app.domain import (
    AgentRole,
    ArchiveReason,
    CandidateCategory,
    ConfidenceLevel,
    EvaluationDecision,
    EvaluationResult,
    EvaluationType,
    EventCluster,
    LaterOutcome,
    PriorityLevel,
    RunPhase,
    RunState,
    WatchTier,
)
from app.domain.base import utc_now
from app.watchlist.materialization import (
    WatchlistMaterializationContext,
    WatchlistMaterializationResult,
    WatchlistOutputMaterializer,
)


WATCH_DECISIONS = {
    EvaluationDecision.SELECT_EARLY_SIGNAL,
    EvaluationDecision.SHORT_WATCH,
    EvaluationDecision.FOLLOWUP_LATER,
}


@dataclass
class WatchlistLifecycleService:
    """Apply deterministic memory lifecycle operations around Watchlist Agent tasks."""

    context: WatchlistMaterializationContext

    def __post_init__(self) -> None:
        self.materializer = WatchlistOutputMaterializer(self.context)

    def expire_due_items(
        self,
        *,
        run: RunState,
        phase: RunPhase = RunPhase.WATCHLIST_UPDATE,
    ) -> WatchlistMaterializationResult:
        """Archive active/reactivated watch items whose watch window has expired."""

        self.context.session.flush()
        now = utc_now()
        due_items = self.materializer.watchlist.list_active_due(before=now)
        archive_drafts = [
            ArchiveDraft(
                original_watchlist_id=item.id,
                original_cluster_id=item.cluster_ids[0] if item.cluster_ids else None,
                thread_id=item.thread_id,
                archive_reason=ArchiveReason.TTL_EXPIRED,
                final_state=f"Watch window expired for {item.topic}.",
                reactivation_hint=(
                    item.reactivation_rules[0]
                    if item.reactivation_rules
                    else "Reactivate if new evidence appears."
                ),
                evidence_ids=item.evidence_ids,
                metadata={"lifecycle": "expire_due_items"},
            )
            for item in due_items
            if item.run_id == run.id
        ]
        if not archive_drafts:
            return WatchlistMaterializationResult()
        return self.materializer.materialize_drafts(
            run=run,
            phase=phase,
            agent_role=AgentRole.SYSTEM,
            archive_drafts=archive_drafts,
        )

    def sync_evaluation_memory(
        self,
        *,
        run: RunState,
        phase: RunPhase = RunPhase.WATCHLIST_UPDATE,
    ) -> WatchlistMaterializationResult:
        """Create default memory records from evaluator decisions when no agent task runs."""

        self.context.session.flush()
        full_state = self.context.runs.get_full_state(run.id)
        clusters_by_id = {cluster.id: cluster for cluster in full_state.clusters}
        watched_evaluation_ids = {
            item.metadata.get("source_evaluation_id")
            for item in full_state.watchlist
            if item.metadata.get("source_evaluation_id")
        }
        archived_evaluation_ids = {
            archive.metadata.get("source_evaluation_id")
            for archive in full_state.archives
            if archive.metadata.get("source_evaluation_id")
        }
        threaded_evaluation_ids = {
            thread.metadata.get("source_evaluation_id")
            for thread in full_state.threads
            if thread.metadata.get("source_evaluation_id")
        }
        # Fallback: also track which clusters are already covered,
        # in case the Watchlist Agent created items without source_evaluation_id.
        watched_cluster_ids = {
            cluster_id
            for item in full_state.watchlist
            for cluster_id in item.cluster_ids
        }
        archived_cluster_ids = {
            archive.original_cluster_id
            for archive in full_state.archives
            if archive.original_cluster_id
        }
        threaded_cluster_ids = {
            cluster_id
            for thread in full_state.threads
            for cluster_id in thread.linked_cluster_ids
        }

        watchlist_drafts: list[WatchlistDraft] = []
        archive_drafts: list[ArchiveDraft] = []
        thread_drafts: list[ThreadDraft] = []
        for evaluation in full_state.evaluations:
            cluster = clusters_by_id.get(evaluation.cluster_id)
            if cluster is None:
                continue
            if (
                evaluation.decision in WATCH_DECISIONS
                and evaluation.id not in watched_evaluation_ids
                and evaluation.cluster_id not in watched_cluster_ids
            ):
                watchlist_drafts.append(self._watchlist_draft(evaluation, cluster))
            if (
                evaluation.decision == EvaluationDecision.ARCHIVE
                and evaluation.id not in archived_evaluation_ids
                and evaluation.cluster_id not in archived_cluster_ids
            ):
                archive_drafts.append(self._archive_draft(evaluation, cluster))
            if (
                evaluation.decision == EvaluationDecision.SELECT_CONFIRMED
                and evaluation.id not in threaded_evaluation_ids
                and evaluation.cluster_id not in threaded_cluster_ids
            ):
                thread_drafts.append(self._confirmed_thread_draft(evaluation, cluster))

        if not (watchlist_drafts or archive_drafts or thread_drafts):
            return WatchlistMaterializationResult()
        return self.materializer.materialize_drafts(
            run=run,
            phase=phase,
            agent_role=AgentRole.SYSTEM,
            watchlist_drafts=watchlist_drafts,
            archive_drafts=archive_drafts,
            thread_drafts=thread_drafts,
        )

    def _watchlist_draft(
        self,
        evaluation: EvaluationResult,
        cluster: EventCluster,
    ) -> WatchlistDraft:
        tier = self._watch_tier(evaluation, cluster)
        followups = evaluation.required_followups or [
            "Reactivate if new independent evidence changes the signal state."
        ]
        open_questions = evaluation.required_followups + evaluation.missing_evidence
        return WatchlistDraft(
            source_evaluation_id=evaluation.id,
            cluster_ids=[cluster.id],
            topic=cluster.title,
            thesis=cluster.canonical_claim,
            watch_tier=tier,
            priority=self._priority(evaluation.total_score),
            ttl_days=self._ttl_days(tier),
            revisit_cadence_days=1 if tier == WatchTier.SHORT else 3,
            reactivation_rules=followups,
            open_questions=open_questions or followups,
            entities=cluster.entities,
            topics=cluster.topics,
            evidence_ids=cluster.evidence_ids,
            metadata={"lifecycle": "sync_evaluation_memory"},
        )

    @staticmethod
    def _archive_draft(
        evaluation: EvaluationResult,
        cluster: EventCluster,
    ) -> ArchiveDraft:
        reason = (
            ArchiveReason.LOW_VALUE
            if evaluation.total_score < 5
            else ArchiveReason.NO_NEW_SIGNAL
        )
        return ArchiveDraft(
            original_cluster_id=cluster.id,
            archive_reason=reason,
            final_state=f"Evaluator archived cluster after {evaluation.decision.value}.",
            reactivation_hint=(
                evaluation.required_followups[0]
                if evaluation.required_followups
                else "Reactivate if new high-quality evidence appears."
            ),
            evidence_ids=cluster.evidence_ids,
            metadata={
                "source_evaluation_id": evaluation.id,
                "lifecycle": "sync_evaluation_memory",
            },
        )

    def _confirmed_thread_draft(
        self,
        evaluation: EvaluationResult,
        cluster: EventCluster,
    ) -> ThreadDraft:
        return ThreadDraft(
            title=cluster.title,
            importance=self._priority(evaluation.total_score),
            entities=cluster.entities,
            topics=cluster.topics,
            current_thesis=cluster.canonical_claim,
            timeline=[
                ThreadTimelineDraft(
                    summary=f"Confirmed event evaluated: {cluster.title}",
                    confidence_at_time=ConfidenceLevel.HIGH,
                    later_outcome=LaterOutcome.CONFIRMED,
                    cluster_id=cluster.id,
                    evidence_ids=cluster.evidence_ids,
                )
            ],
            linked_cluster_ids=[cluster.id],
            metadata={
                "source_evaluation_id": evaluation.id,
                "lifecycle": "sync_evaluation_memory",
            },
        )

    @staticmethod
    def _watch_tier(evaluation: EvaluationResult, cluster: EventCluster) -> WatchTier:
        if cluster.category == CandidateCategory.EARLY_SIGNAL:
            return WatchTier.SHORT
        if evaluation.evaluator_type == EvaluationType.MARKET:
            return WatchTier.STRATEGIC
        return WatchTier.EVENT

    @staticmethod
    def _ttl_days(tier: WatchTier) -> int:
        if tier == WatchTier.SHORT:
            return 7
        if tier == WatchTier.EVENT:
            return 14
        return 45

    @staticmethod
    def _priority(score: float) -> PriorityLevel:
        if score >= 8.5:
            return PriorityLevel.CRITICAL
        if score >= 7:
            return PriorityLevel.HIGH
        if score >= 5:
            return PriorityLevel.MEDIUM
        return PriorityLevel.LOW
