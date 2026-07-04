"""Materialize Watchlist Agent outputs into memory records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Protocol

from sqlalchemy.orm import Session

from app.agents.outputs import ArchiveDraft, ThreadDraft, ThreadTimelineDraft, WatchlistAgentOutput, WatchlistDraft
from app.agents.schemas import AgentRunResult
from app.core.ids import IdPrefix, deterministic_id
from app.domain import (
    AgentRole,
    ArchivedSignal,
    ArchiveReason,
    ConfidenceLevel,
    EventCluster,
    IntelligenceThread,
    LaterOutcome,
    PriorityLevel,
    RunPhase,
    RunState,
    ThreadStatus,
    ThreadTimelineEntry,
    TraceEventType,
    TraceStatus,
    WatchHistoryEntry,
    WatchStatus,
    WatchTier,
    WatchlistItem,
)
from app.domain.base import utc_now
from app.exceptions import HarnessError
from app.repositories import (
    ArchivedSignalRepository,
    EvaluationRepository,
    EventClusterRepository,
    EvidenceRepository,
    IntelligenceThreadRepository,
    RunRepository,
    WatchlistRepository,
)
from app.services import TraceService


DEFAULT_TTL_DAYS = {
    WatchTier.SHORT: 7,
    WatchTier.EVENT: 14,
    WatchTier.STRATEGIC: 45,
}


class WatchlistMaterializationContext(Protocol):
    """Context interface required by WatchlistOutputMaterializer."""

    session: Session
    trace_service: TraceService
    runs: RunRepository

    def persist_run(self, run: RunState) -> RunState:
        """Persist an updated RunState."""


@dataclass
class WatchlistMaterializationResult:
    """Domain objects created or updated from Watchlist Agent output."""

    watchlist_ids: list[str] = field(default_factory=list)
    archive_ids: list[str] = field(default_factory=list)
    thread_ids: list[str] = field(default_factory=list)


class WatchlistOutputMaterializer:
    """Persist Watchlist Agent drafts into watchlist, archive, and thread records."""

    def __init__(self, context: WatchlistMaterializationContext):
        self.context = context
        self.watchlist = WatchlistRepository(context.session)
        self.archives = ArchivedSignalRepository(context.session)
        self.threads = IntelligenceThreadRepository(context.session)
        self.clusters = EventClusterRepository(context.session)
        self.evaluations = EvaluationRepository(context.session)
        self.evidence = EvidenceRepository(context.session)

    def materialize(
        self,
        *,
        run: RunState,
        phase: RunPhase,
        agent_role: AgentRole,
        result: AgentRunResult,
    ) -> WatchlistMaterializationResult:
        """Materialize WatchlistAgentOutput drafts into Connor memory state."""

        self.context.session.flush()
        if phase != RunPhase.WATCHLIST_UPDATE:
            raise HarnessError(
                f"watchlist materialization requires watchlist_update phase, got {phase.value}"
            )
        if agent_role != AgentRole.WATCHLIST_AGENT:
            raise HarnessError(
                f"watchlist materialization requires watchlist_agent role, got {agent_role.value}"
            )
        if not isinstance(result.structured_output, WatchlistAgentOutput):
            return WatchlistMaterializationResult()
        return self.materialize_drafts(
            run=run,
            phase=phase,
            agent_role=agent_role,
            watchlist_drafts=result.structured_output.watchlist_drafts,
            archive_drafts=result.structured_output.archive_drafts,
            thread_drafts=result.structured_output.thread_drafts,
        )

    def materialize_drafts(
        self,
        *,
        run: RunState,
        phase: RunPhase,
        agent_role: AgentRole,
        watchlist_drafts: list[WatchlistDraft] | None = None,
        archive_drafts: list[ArchiveDraft] | None = None,
        thread_drafts: list[ThreadDraft] | None = None,
    ) -> WatchlistMaterializationResult:
        """Materialize drafts produced by an agent or deterministic lifecycle policy."""

        materialized = WatchlistMaterializationResult()
        for draft in watchlist_drafts or []:
            item = self._create_or_update_watchlist(run=run, draft=draft)
            self.watchlist.add(item)
            materialized.watchlist_ids.append(item.id)
            if item.thread_id:
                materialized.thread_ids.append(item.thread_id)
                self.context.session.flush()
                thread = self.threads.get(item.thread_id)
                if thread is not None:
                    self._trace_thread(run=run, phase=phase, agent_role=agent_role, thread=thread)
            self.context.trace_service.record_event(
                run_id=run.id,
                phase=phase,
                agent_role=agent_role,
                event_type=TraceEventType.WATCHLIST_UPDATED,
                status=TraceStatus.SUCCEEDED,
                summary=f"Watchlist item updated: {item.topic}",
                created_objects=[item],
                output_payload=item.model_dump(mode="json"),
                metadata={"watchlist_id": item.id, "status": item.status.value},
            )

        for draft in archive_drafts or []:
            archive = self._create_or_update_archive(run=run, draft=draft)
            self.archives.add(archive)
            materialized.archive_ids.append(archive.id)
            if archive.thread_id:
                materialized.thread_ids.append(archive.thread_id)
                self.context.session.flush()
                thread = self.threads.get(archive.thread_id)
                if thread is not None:
                    self._trace_thread(run=run, phase=phase, agent_role=agent_role, thread=thread)
            self.context.trace_service.record_event(
                run_id=run.id,
                phase=phase,
                agent_role=agent_role,
                event_type=TraceEventType.ARCHIVE_CREATED,
                status=TraceStatus.SUCCEEDED,
                summary=f"Archived signal: {archive.final_state}",
                created_objects=[archive],
                output_payload=archive.model_dump(mode="json"),
                metadata={
                    "archive_id": archive.id,
                    "archive_reason": archive.archive_reason.value,
                },
            )

        for draft in thread_drafts or []:
            thread = self._create_or_update_thread(draft)
            self.threads.add(thread)
            materialized.thread_ids.append(thread.id)
            self._trace_thread(run=run, phase=phase, agent_role=agent_role, thread=thread)

        materialized.watchlist_ids = self._dedupe(materialized.watchlist_ids)
        materialized.archive_ids = self._dedupe(materialized.archive_ids)
        materialized.thread_ids = self._dedupe(materialized.thread_ids)
        self._update_run_lineage(run.id, materialized)
        self.context.session.flush()
        return materialized

    def _create_or_update_watchlist(self, *, run: RunState, draft: WatchlistDraft) -> WatchlistItem:
        now = utc_now()
        cluster_ids, evidence_ids, entities, topics = self._lineage_from_watch_draft(run.id, draft)
        ttl_days = draft.ttl_days or DEFAULT_TTL_DAYS[draft.watch_tier]
        watchlist_id = draft.watchlist_id or deterministic_id(
            IdPrefix.WATCHLIST,
            {
                "run_id": run.id,
                "source_evaluation_id": draft.source_evaluation_id,
                "cluster_ids": sorted(cluster_ids),
                "topic": draft.topic,
            },
        )
        existing = self.watchlist.get(watchlist_id)
        history_entry = WatchHistoryEntry(
            at=now,
            summary="Watchlist tracking item created or refreshed.",
            evidence_ids=evidence_ids,
        )
        thread_id = draft.thread_id
        if thread_id is None:
            thread = self._thread_for_watch(
                watchlist_id=watchlist_id,
                draft=draft,
                cluster_ids=cluster_ids,
                evidence_ids=evidence_ids,
            )
            self.threads.add(thread)
            thread_id = thread.id

        if existing is not None:
            status = (
                WatchStatus.REACTIVATED
                if existing.status in {WatchStatus.EXPIRED, WatchStatus.ARCHIVED, WatchStatus.COOLING}
                else WatchStatus.ACTIVE
            )
            return existing.model_copy(
                update={
                    "topic": draft.topic,
                    "thesis": draft.thesis,
                    "watch_tier": draft.watch_tier,
                    "status": status,
                    "priority": draft.priority,
                    "ttl_days": ttl_days,
                    "watch_until": now + timedelta(days=ttl_days),
                    "revisit_cadence_days": draft.revisit_cadence_days,
                    "last_checked_at": now,
                    "last_signal_at": now,
                    "reactivation_rules": self._dedupe(
                        existing.reactivation_rules + draft.reactivation_rules
                    ),
                    "open_questions": self._dedupe(existing.open_questions + draft.open_questions),
                    "entities": self._dedupe(existing.entities + entities + draft.entities),
                    "topics": self._dedupe(existing.topics + topics + draft.topics),
                    "evidence_ids": self._dedupe(existing.evidence_ids + evidence_ids),
                    "cluster_ids": self._dedupe(existing.cluster_ids + cluster_ids),
                    "thread_id": thread_id,
                    "history": existing.history + [history_entry],
                    "metadata": {
                        **existing.metadata,
                        **draft.metadata,
                        "source_evaluation_id": draft.source_evaluation_id,
                        "materialized_by": "WatchlistOutputMaterializer",
                    },
                    "updated_at": now,
                }
            )

        return WatchlistItem(
            id=watchlist_id,
            run_id=run.id,
            topic=draft.topic,
            thesis=draft.thesis,
            watch_tier=draft.watch_tier,
            status=WatchStatus.ACTIVE,
            priority=draft.priority,
            ttl_days=ttl_days,
            watch_until=now + timedelta(days=ttl_days),
            revisit_cadence_days=draft.revisit_cadence_days,
            last_checked_at=now,
            last_signal_at=now,
            reactivation_rules=draft.reactivation_rules,
            open_questions=draft.open_questions,
            entities=self._dedupe(entities + draft.entities),
            topics=self._dedupe(topics + draft.topics),
            evidence_ids=evidence_ids,
            cluster_ids=cluster_ids,
            thread_id=thread_id,
            history=[history_entry],
            metadata={
                **draft.metadata,
                "source_evaluation_id": draft.source_evaluation_id,
                "materialized_by": "WatchlistOutputMaterializer",
            },
            created_at=now,
        )

    def _create_or_update_archive(self, *, run: RunState, draft: ArchiveDraft) -> ArchivedSignal:
        now = utc_now()
        evidence_ids = list(draft.evidence_ids)
        thread_id = draft.thread_id
        if draft.original_cluster_id:
            cluster = self._cluster_for_run(run.id, draft.original_cluster_id)
            evidence_ids = self._dedupe(evidence_ids + cluster.evidence_ids)
        if draft.original_watchlist_id:
            watch = self._watch_for_run(run.id, draft.original_watchlist_id)
            evidence_ids = self._dedupe(evidence_ids + watch.evidence_ids)
            thread_id = thread_id or watch.thread_id
            watch_status = (
                WatchStatus.EXPIRED
                if draft.archive_reason == ArchiveReason.TTL_EXPIRED
                else WatchStatus.ARCHIVED
            )
            self.watchlist.add(
                watch.model_copy(
                    update={
                        "status": watch_status,
                        "updated_at": now,
                        "history": watch.history
                        + [
                            WatchHistoryEntry(
                                at=now,
                                summary=f"Watch item archived: {draft.archive_reason.value}.",
                                evidence_ids=evidence_ids,
                            )
                        ],
                    }
                )
            )

        for evidence_id in evidence_ids:
            self._require_evidence_for_run(run.id, evidence_id)

        archive_id = draft.archive_id or deterministic_id(
            IdPrefix.ARCHIVE,
            {
                "run_id": run.id,
                "cluster_id": draft.original_cluster_id,
                "watchlist_id": draft.original_watchlist_id,
                "reason": draft.archive_reason.value,
            },
        )
        if thread_id is None:
            thread = self._thread_for_archive(
                archive_id=archive_id,
                draft=draft,
                evidence_ids=evidence_ids,
            )
            self.threads.add(thread)
            thread_id = thread.id
        else:
            existing_thread = self.threads.get(thread_id)
            if existing_thread is not None:
                thread = self._merge_thread(
                    existing_thread,
                    timeline=[
                        ThreadTimelineEntry(
                            event_at=now,
                            summary=f"Archived signal: {draft.final_state}",
                            confidence_at_time=ConfidenceLevel.LOW,
                            later_outcome=LaterOutcome.UNRESOLVED,
                            cluster_id=draft.original_cluster_id,
                            watchlist_id=draft.original_watchlist_id,
                            archive_id=archive_id,
                            evidence_ids=evidence_ids,
                        )
                    ],
                    linked_archive_ids=[archive_id],
                )
                self.threads.add(thread)

        existing = self.archives.get(archive_id)
        if existing is not None:
            return existing.model_copy(
                update={
                    "thread_id": thread_id,
                    "archive_reason": draft.archive_reason,
                    "archived_at": now,
                    "final_state": draft.final_state,
                    "reactivation_hint": draft.reactivation_hint,
                    "evidence_ids": self._dedupe(existing.evidence_ids + evidence_ids),
                    "metadata": {
                        **existing.metadata,
                        **draft.metadata,
                        "materialized_by": "WatchlistOutputMaterializer",
                    },
                    "updated_at": now,
                }
            )

        return ArchivedSignal(
            id=archive_id,
            run_id=run.id,
            original_cluster_id=draft.original_cluster_id,
            original_watchlist_id=draft.original_watchlist_id,
            thread_id=thread_id,
            archive_reason=draft.archive_reason,
            archived_at=now,
            final_state=draft.final_state,
            reactivation_hint=draft.reactivation_hint,
            evidence_ids=evidence_ids,
            metadata={
                **draft.metadata,
                "materialized_by": "WatchlistOutputMaterializer",
            },
            created_at=now,
        )

    def _create_or_update_thread(self, draft: ThreadDraft) -> IntelligenceThread:
        thread_id = draft.thread_id or deterministic_id(
            IdPrefix.THREAD,
            {
                "title": draft.title,
                "entities": sorted(draft.entities),
                "topics": sorted(draft.topics),
            },
        )
        timeline = [self._timeline_entry(entry) for entry in draft.timeline]
        existing = self.threads.get(thread_id)
        if existing is None:
            return IntelligenceThread(
                id=thread_id,
                title=draft.title,
                status=draft.status,
                importance=draft.importance,
                entities=draft.entities,
                topics=draft.topics,
                current_thesis=draft.current_thesis,
                timeline=timeline,
                open_questions=draft.open_questions,
                linked_cluster_ids=self._dedupe(
                    draft.linked_cluster_ids
                    + [entry.cluster_id for entry in timeline if entry.cluster_id]
                ),
                linked_watchlist_ids=self._dedupe(
                    draft.linked_watchlist_ids
                    + [entry.watchlist_id for entry in timeline if entry.watchlist_id]
                ),
                linked_archive_ids=self._dedupe(
                    draft.linked_archive_ids
                    + [entry.archive_id for entry in timeline if entry.archive_id]
                ),
                linked_report_ids=self._dedupe(
                    draft.linked_report_ids
                    + [entry.report_id for entry in timeline if entry.report_id]
                ),
                metadata={**draft.metadata, "materialized_by": "WatchlistOutputMaterializer"},
                created_at=utc_now(),
            )
        return self._merge_thread(
            existing.model_copy(
                update={
                    "title": draft.title,
                    "status": draft.status,
                    "importance": draft.importance,
                    "current_thesis": draft.current_thesis,
                    "entities": self._dedupe(existing.entities + draft.entities),
                    "topics": self._dedupe(existing.topics + draft.topics),
                    "open_questions": self._dedupe(
                        existing.open_questions + draft.open_questions
                    ),
                    "metadata": {
                        **existing.metadata,
                        **draft.metadata,
                        "materialized_by": "WatchlistOutputMaterializer",
                    },
                    "updated_at": utc_now(),
                }
            ),
            timeline=timeline,
            linked_cluster_ids=draft.linked_cluster_ids,
            linked_watchlist_ids=draft.linked_watchlist_ids,
            linked_archive_ids=draft.linked_archive_ids,
            linked_report_ids=draft.linked_report_ids,
        )

    def _lineage_from_watch_draft(
        self,
        run_id: str,
        draft: WatchlistDraft,
    ) -> tuple[list[str], list[str], list[str], list[str]]:
        cluster_ids = list(draft.cluster_ids)
        evidence_ids = list(draft.evidence_ids)
        entities: list[str] = []
        topics: list[str] = []
        if draft.source_evaluation_id:
            try:
                evaluation = self.evaluations.require(draft.source_evaluation_id)
            except LookupError as exc:
                raise HarnessError(str(exc)) from exc
            if evaluation.run_id != run_id:
                raise HarnessError(
                    f"evaluation {draft.source_evaluation_id} does not belong to run {run_id}"
                )
            cluster_ids.append(evaluation.cluster_id)

        for cluster_id in self._dedupe(cluster_ids):
            cluster = self._cluster_for_run(run_id, cluster_id)
            evidence_ids.extend(cluster.evidence_ids)
            entities.extend(cluster.entities)
            topics.extend(cluster.topics)

        for evidence_id in self._dedupe(evidence_ids):
            self._require_evidence_for_run(run_id, evidence_id)

        return (
            self._dedupe(cluster_ids),
            self._dedupe(evidence_ids),
            self._dedupe(entities),
            self._dedupe(topics),
        )

    def _thread_for_watch(
        self,
        *,
        watchlist_id: str,
        draft: WatchlistDraft,
        cluster_ids: list[str],
        evidence_ids: list[str],
    ) -> IntelligenceThread:
        thread_id = deterministic_id(
            IdPrefix.THREAD,
            {
                "topic": draft.topic,
                "cluster_ids": sorted(cluster_ids),
                "watchlist_id": watchlist_id,
            },
        )
        timeline = [
            ThreadTimelineEntry(
                event_at=utc_now(),
                summary=f"Watch item opened: {draft.topic}",
                confidence_at_time=ConfidenceLevel.LOW,
                later_outcome=LaterOutcome.PENDING,
                cluster_id=cluster_ids[0] if cluster_ids else None,
                watchlist_id=watchlist_id,
                evidence_ids=evidence_ids,
            )
        ]
        existing = self.threads.get(thread_id)
        if existing is not None:
            thread = self._merge_thread(
                existing,
                timeline=timeline,
                linked_cluster_ids=cluster_ids,
                linked_watchlist_ids=[watchlist_id],
            )
            return thread
        thread = IntelligenceThread(
            id=thread_id,
            title=draft.topic,
            status=ThreadStatus.ACTIVE,
            importance=draft.priority,
            entities=draft.entities,
            topics=draft.topics,
            current_thesis=draft.thesis,
            timeline=timeline,
            open_questions=draft.open_questions,
            linked_cluster_ids=cluster_ids,
            linked_watchlist_ids=[watchlist_id],
            metadata={"created_from_watchlist_id": watchlist_id},
            created_at=utc_now(),
        )
        return thread

    def _thread_for_archive(
        self,
        *,
        archive_id: str,
        draft: ArchiveDraft,
        evidence_ids: list[str],
    ) -> IntelligenceThread:
        title = f"Archived signal: {draft.original_cluster_id or draft.original_watchlist_id}"
        timeline = [
            ThreadTimelineEntry(
                event_at=utc_now(),
                summary=f"Archived signal: {draft.final_state}",
                confidence_at_time=ConfidenceLevel.LOW,
                later_outcome=LaterOutcome.UNRESOLVED,
                cluster_id=draft.original_cluster_id,
                watchlist_id=draft.original_watchlist_id,
                archive_id=archive_id,
                evidence_ids=evidence_ids,
            )
        ]
        return IntelligenceThread(
            id=deterministic_id(
                IdPrefix.THREAD,
                {
                    "archive_id": archive_id,
                    "cluster_id": draft.original_cluster_id,
                    "watchlist_id": draft.original_watchlist_id,
                },
            ),
            title=title,
            status=ThreadStatus.ARCHIVED,
            importance=PriorityLevel.LOW,
            current_thesis=draft.final_state,
            timeline=timeline,
            linked_cluster_ids=[draft.original_cluster_id] if draft.original_cluster_id else [],
            linked_watchlist_ids=[draft.original_watchlist_id] if draft.original_watchlist_id else [],
            linked_archive_ids=[archive_id],
            metadata={"created_from_archive_id": archive_id},
            created_at=utc_now(),
        )

    def _trace_thread(
        self,
        *,
        run: RunState,
        phase: RunPhase,
        agent_role: AgentRole,
        thread: IntelligenceThread,
    ) -> None:
        self.context.trace_service.record_event(
            run_id=run.id,
            phase=phase,
            agent_role=agent_role,
            event_type=TraceEventType.THREAD_UPDATED,
            status=TraceStatus.SUCCEEDED,
            summary=f"Intelligence thread updated: {thread.title}",
            created_objects=[thread],
            output_payload=thread.model_dump(mode="json"),
            metadata={"thread_id": thread.id, "status": thread.status.value},
        )

    @staticmethod
    def _timeline_entry(draft: ThreadTimelineDraft) -> ThreadTimelineEntry:
        return ThreadTimelineEntry(
            event_at=draft.event_at or utc_now(),
            summary=draft.summary,
            confidence_at_time=draft.confidence_at_time,
            later_outcome=draft.later_outcome,
            cluster_id=draft.cluster_id,
            watchlist_id=draft.watchlist_id,
            archive_id=draft.archive_id,
            report_id=draft.report_id,
            evidence_ids=draft.evidence_ids,
        )

    def _merge_thread(
        self,
        thread: IntelligenceThread,
        *,
        timeline: list[ThreadTimelineEntry] | None = None,
        linked_cluster_ids: list[str] | None = None,
        linked_watchlist_ids: list[str] | None = None,
        linked_archive_ids: list[str] | None = None,
        linked_report_ids: list[str] | None = None,
    ) -> IntelligenceThread:
        return thread.model_copy(
            update={
                "timeline": self._merge_timeline(thread.timeline, timeline or []),
                "linked_cluster_ids": self._dedupe(
                    thread.linked_cluster_ids + (linked_cluster_ids or [])
                ),
                "linked_watchlist_ids": self._dedupe(
                    thread.linked_watchlist_ids + (linked_watchlist_ids or [])
                ),
                "linked_archive_ids": self._dedupe(
                    thread.linked_archive_ids + (linked_archive_ids or [])
                ),
                "linked_report_ids": self._dedupe(
                    thread.linked_report_ids + (linked_report_ids or [])
                ),
                "updated_at": utc_now(),
            }
        )

    @staticmethod
    def _merge_timeline(
        existing: list[ThreadTimelineEntry],
        updates: list[ThreadTimelineEntry],
    ) -> list[ThreadTimelineEntry]:
        merged = list(existing)
        keys = {
            (
                item.summary,
                item.event_at,
                item.cluster_id,
                item.watchlist_id,
                item.archive_id,
                item.report_id,
            )
            for item in merged
        }
        for item in updates:
            key = (
                item.summary,
                item.event_at,
                item.cluster_id,
                item.watchlist_id,
                item.archive_id,
                item.report_id,
            )
            if key not in keys:
                merged.append(item)
                keys.add(key)
        return merged

    def _cluster_for_run(self, run_id: str, cluster_id: str) -> EventCluster:
        try:
            cluster = self.clusters.require(cluster_id)
        except LookupError as exc:
            raise HarnessError(str(exc)) from exc
        if cluster.run_id != run_id:
            raise HarnessError(f"cluster {cluster_id} does not belong to run {run_id}")
        return cluster

    def _watch_for_run(self, run_id: str, watchlist_id: str) -> WatchlistItem:
        try:
            watch = self.watchlist.require(watchlist_id)
        except LookupError as exc:
            raise HarnessError(str(exc)) from exc
        if watch.run_id != run_id:
            raise HarnessError(f"watchlist item {watchlist_id} does not belong to run {run_id}")
        return watch

    def _require_evidence_for_run(self, run_id: str, evidence_id: str) -> None:
        try:
            evidence = self.evidence.require(evidence_id)
        except LookupError as exc:
            raise HarnessError(str(exc)) from exc
        if evidence.run_id != run_id:
            raise HarnessError(f"evidence {evidence_id} does not belong to run {run_id}")

    def _update_run_lineage(
        self,
        run_id: str,
        materialized: WatchlistMaterializationResult,
    ) -> None:
        run = self.context.runs.require(run_id)
        updated = run.model_copy(
            update={
                "watchlist_ids": self._dedupe(run.watchlist_ids + materialized.watchlist_ids),
                "archived_signal_ids": self._dedupe(
                    run.archived_signal_ids + materialized.archive_ids
                ),
                "thread_ids": self._dedupe(run.thread_ids + materialized.thread_ids),
                "metadata": {
                    **run.metadata,
                    "watchlist_materialization": {
                        "watchlist_ids": materialized.watchlist_ids,
                        "archive_ids": materialized.archive_ids,
                        "thread_ids": materialized.thread_ids,
                    },
                },
            }
        )
        self.context.persist_run(updated)

    @staticmethod
    def _dedupe(values: list[str | None]) -> list[str]:
        deduped: list[str] = []
        for value in values:
            if value and value not in deduped:
                deduped.append(value)
        return deduped
