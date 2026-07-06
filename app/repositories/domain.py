"""Repositories for non-run domain records."""

from sqlalchemy import select

from app.db.models import (
    ArchivedSignalRecord,
    ArtifactRecord,
    CandidateItemRecord,
    DailyReportRecord,
    EvaluationResultRecord,
    EvidenceItemRecord,
    EventClusterRecord,
    IntelligenceThreadRecord,
    ModelCallRecordORM,
    ReviewIssueRecord,
    ReviewResultRecord,
    ToolCallRecordORM,
    TraceEventRecord,
    WatchlistItemRecord,
)
from app.domain import (
    ArchivedSignal,
    Artifact,
    CandidateItem,
    DailyReport,
    EvaluationResult,
    EvidenceItem,
    EventCluster,
    IntelligenceThread,
    ModelCallRecord,
    ReviewIssue,
    ReviewResult,
    ToolCallRecord,
    TraceEvent,
    WatchlistItem,
    WatchStatus,
)
from app.repositories.base import DomainRepository, enum_value


class EvidenceRepository(DomainRepository[EvidenceItem, EvidenceItemRecord]):
    domain_model = EvidenceItem
    record_model = EvidenceItemRecord

    def to_record(self, obj: EvidenceItem) -> EvidenceItemRecord:
        return EvidenceItemRecord(
            **self._common_values(obj),
            run_id=obj.run_id,
            source_type=enum_value(obj.source_type),
            source_name=obj.source_name,
            access_level=enum_value(obj.access_level),
            strength=enum_value(obj.strength),
            url=obj.url,
            title=obj.title,
            published_at=obj.published_at,
            retrieved_at=obj.retrieved_at,
            raw_hash=obj.raw_hash,
        )

    def list_urls_in_run(self, run_id: str) -> set[str]:
        """Return the set of non-null, non-empty URLs already persisted for a run."""
        stmt = select(EvidenceItemRecord.url).where(
            EvidenceItemRecord.run_id == run_id,
            EvidenceItemRecord.url.isnot(None),
            EvidenceItemRecord.url != "",
        )
        rows = self.session.execute(stmt).all()
        return {row[0] for row in rows if row[0]}


class CandidateRepository(DomainRepository[CandidateItem, CandidateItemRecord]):
    domain_model = CandidateItem
    record_model = CandidateItemRecord

    def to_record(self, obj: CandidateItem) -> CandidateItemRecord:
        return CandidateItemRecord(
            **self._common_values(obj),
            run_id=obj.run_id,
            category=enum_value(obj.category),
            signal_status=enum_value(obj.signal_status),
            claim_summary=obj.claim_summary,
            created_by_agent=enum_value(obj.created_by_agent),
            uncertainty=enum_value(obj.uncertainty),
            evidence_strength=enum_value(obj.evidence_strength),
        )


class EventClusterRepository(DomainRepository[EventCluster, EventClusterRecord]):
    domain_model = EventCluster
    record_model = EventClusterRecord
    warn_on_payload_merge = False

    def to_record(self, obj: EventCluster) -> EventClusterRecord:
        return EventClusterRecord(
            **self._common_values(obj),
            run_id=obj.run_id,
            category=enum_value(obj.category),
            title=obj.title,
            canonical_claim=obj.canonical_claim,
            dedupe_key=obj.dedupe_key,
            selected=obj.selected,
        )

    def get_by_dedupe_key(self, dedupe_key: str) -> EventCluster | None:
        stmt = select(EventClusterRecord).where(EventClusterRecord.dedupe_key == dedupe_key)
        record = self.session.scalars(stmt).first()
        return None if record is None else self.to_domain(record)


class EvaluationRepository(DomainRepository[EvaluationResult, EvaluationResultRecord]):
    domain_model = EvaluationResult
    record_model = EvaluationResultRecord

    def to_record(self, obj: EvaluationResult) -> EvaluationResultRecord:
        return EvaluationResultRecord(
            **self._common_values(obj),
            run_id=obj.run_id,
            cluster_id=obj.cluster_id,
            evaluator_type=enum_value(obj.evaluator_type),
            created_by_agent=enum_value(obj.created_by_agent),
            total_score=obj.total_score,
            decision=enum_value(obj.decision),
            reasoning_summary=obj.reasoning_summary,
            write_policy=enum_value(obj.write_policy) if obj.write_policy else None,
        )

    def list_by_cluster(self, cluster_id: str) -> list[EvaluationResult]:
        stmt = select(EvaluationResultRecord).where(EvaluationResultRecord.cluster_id == cluster_id)
        return [self.to_domain(record) for record in self.session.scalars(stmt)]


class WatchlistRepository(DomainRepository[WatchlistItem, WatchlistItemRecord]):
    domain_model = WatchlistItem
    record_model = WatchlistItemRecord
    warn_on_payload_merge = False

    def to_record(self, obj: WatchlistItem) -> WatchlistItemRecord:
        return WatchlistItemRecord(
            **self._common_values(obj),
            run_id=obj.run_id,
            topic=obj.topic,
            watch_tier=enum_value(obj.watch_tier),
            status=enum_value(obj.status),
            priority=enum_value(obj.priority),
            ttl_days=obj.ttl_days,
            watch_until=obj.watch_until,
            last_checked_at=obj.last_checked_at,
            last_signal_at=obj.last_signal_at,
            thread_id=obj.thread_id,
        )

    def list_active_due(self, *, before) -> list[WatchlistItem]:
        stmt = select(WatchlistItemRecord).where(
            WatchlistItemRecord.status.in_([WatchStatus.ACTIVE.value, WatchStatus.REACTIVATED.value]),
            WatchlistItemRecord.watch_until <= before,
        )
        return [self.to_domain(record) for record in self.session.scalars(stmt)]

    def list_active_due_for_run(self, *, before, run_id: str) -> list[WatchlistItem]:
        """Return active/reactivated items due by *before* for a specific run."""
        stmt = select(WatchlistItemRecord).where(
            WatchlistItemRecord.status.in_([WatchStatus.ACTIVE.value, WatchStatus.REACTIVATED.value]),
            WatchlistItemRecord.watch_until <= before,
            WatchlistItemRecord.run_id == run_id,
        )
        return [self.to_domain(record) for record in self.session.scalars(stmt)]

    def list_by_statuses(self, statuses: list[str]) -> list[WatchlistItem]:
        stmt = (
            select(WatchlistItemRecord)
            .where(WatchlistItemRecord.status.in_(statuses))
            .order_by(WatchlistItemRecord.created_at)
        )
        return [self.to_domain(record) for record in self.session.scalars(stmt)]


class ArchivedSignalRepository(DomainRepository[ArchivedSignal, ArchivedSignalRecord]):
    domain_model = ArchivedSignal
    record_model = ArchivedSignalRecord

    def to_record(self, obj: ArchivedSignal) -> ArchivedSignalRecord:
        return ArchivedSignalRecord(
            **self._common_values(obj),
            run_id=obj.run_id,
            original_cluster_id=obj.original_cluster_id,
            original_watchlist_id=obj.original_watchlist_id,
            thread_id=obj.thread_id,
            archive_reason=enum_value(obj.archive_reason),
            archived_at=obj.archived_at,
            final_state=obj.final_state,
        )


class IntelligenceThreadRepository(
    DomainRepository[IntelligenceThread, IntelligenceThreadRecord]
):
    domain_model = IntelligenceThread
    record_model = IntelligenceThreadRecord
    warn_on_payload_merge = False

    def to_record(self, obj: IntelligenceThread) -> IntelligenceThreadRecord:
        return IntelligenceThreadRecord(
            **self._common_values(obj),
            title=obj.title,
            status=enum_value(obj.status),
            importance=enum_value(obj.importance),
            current_thesis=obj.current_thesis,
        )

    def list_by_run(self, run_id: str) -> list[IntelligenceThread]:
        raise NotImplementedError(
            "IntelligenceThread is cross-run and does not have a single run_id. "
            "Use list_by_statuses() instead."
        )

    def list_by_status(self, status: str) -> list[IntelligenceThread]:
        return self.list_by_statuses([status])

    def list_by_statuses(self, statuses: list[str]) -> list[IntelligenceThread]:
        stmt = (
            select(IntelligenceThreadRecord)
            .where(IntelligenceThreadRecord.status.in_(statuses))
            .order_by(IntelligenceThreadRecord.created_at)
        )
        return [self.to_domain(record) for record in self.session.scalars(stmt)]


class DailyReportRepository(DomainRepository[DailyReport, DailyReportRecord]):
    domain_model = DailyReport
    record_model = DailyReportRecord
    warn_on_payload_merge = False

    def to_record(self, obj: DailyReport) -> DailyReportRecord:
        return DailyReportRecord(
            **self._common_values(obj),
            run_id=obj.run_id,
            report_date=obj.report_date,
            title=obj.title,
            status=enum_value(obj.status),
            quality_score=obj.quality_score,
        )


class TraceEventRepository(DomainRepository[TraceEvent, TraceEventRecord]):
    domain_model = TraceEvent
    record_model = TraceEventRecord

    def to_record(self, obj: TraceEvent) -> TraceEventRecord:
        return TraceEventRecord(
            **self._common_values(obj),
            run_id=obj.run_id,
            parent_id=obj.parent_id,
            seq=obj.seq,
            phase=enum_value(obj.phase),
            agent_role=enum_value(obj.agent_role),
            event_type=enum_value(obj.event_type),
            status=enum_value(obj.status),
            summary=obj.summary,
            tool_call_id=obj.tool_call_id,
            model_call_id=obj.model_call_id,
            duration_ms=obj.duration_ms,
        )

    def list_timeline(self, run_id: str) -> list[TraceEvent]:
        stmt = select(TraceEventRecord).where(TraceEventRecord.run_id == run_id).order_by(
            TraceEventRecord.seq
        )
        return [self.to_domain(record) for record in self.session.scalars(stmt)]


class ArtifactRepository(DomainRepository[Artifact, ArtifactRecord]):
    domain_model = Artifact
    record_model = ArtifactRecord

    def to_record(self, obj: Artifact) -> ArtifactRecord:
        return ArtifactRecord(
            **self._common_values(obj),
            run_id=obj.run_id,
            kind=enum_value(obj.kind),
            storage=enum_value(obj.storage),
            uri=obj.uri,
            content_type=obj.content_type,
            sha256=obj.sha256,
            size_bytes=obj.size_bytes,
        )


class ToolCallRepository(DomainRepository[ToolCallRecord, ToolCallRecordORM]):
    domain_model = ToolCallRecord
    record_model = ToolCallRecordORM

    def to_record(self, obj: ToolCallRecord) -> ToolCallRecordORM:
        return ToolCallRecordORM(
            **self._common_values(obj),
            run_id=obj.run_id,
            agent_role=enum_value(obj.agent_role),
            tool_name=obj.tool_name,
            source_type=enum_value(obj.source_type),
            query=obj.query,
            status=enum_value(obj.status),
            started_at=obj.started_at,
            ended_at=obj.ended_at,
            duration_ms=obj.duration_ms,
            trace_event_id=obj.trace_event_id,
            error=obj.error,
        )


class ModelCallRepository(DomainRepository[ModelCallRecord, ModelCallRecordORM]):
    domain_model = ModelCallRecord
    record_model = ModelCallRecordORM

    def to_record(self, obj: ModelCallRecord) -> ModelCallRecordORM:
        return ModelCallRecordORM(
            **self._common_values(obj),
            run_id=obj.run_id,
            agent_role=enum_value(obj.agent_role),
            model_provider=obj.model_provider,
            model_name=obj.model_name,
            status=enum_value(obj.status),
            started_at=obj.started_at,
            ended_at=obj.ended_at,
            duration_ms=obj.duration_ms,
            trace_event_id=obj.trace_event_id,
            input_tokens=obj.input_tokens,
            output_tokens=obj.output_tokens,
            error=obj.error,
        )


class ReviewResultRepository(DomainRepository[ReviewResult, ReviewResultRecord]):
    domain_model = ReviewResult
    record_model = ReviewResultRecord

    def to_record(self, obj: ReviewResult) -> ReviewResultRecord:
        return ReviewResultRecord(
            **self._common_values(obj),
            run_id=obj.run_id,
            report_id=obj.report_id,
            reviewer_agent=enum_value(obj.reviewer_agent),
            decision=enum_value(obj.decision),
            reasoning_summary=obj.reasoning_summary,
        )


class ReviewIssueRepository(DomainRepository[ReviewIssue, ReviewIssueRecord]):
    domain_model = ReviewIssue
    record_model = ReviewIssueRecord

    def to_record(self, obj: ReviewIssue) -> ReviewIssueRecord:
        return ReviewIssueRecord(
            **self._common_values(obj),
            run_id=obj.run_id,
            report_id=obj.report_id,
            priority=obj.priority,
            title=obj.title,
            report_item_id=obj.report_item_id,
        )
