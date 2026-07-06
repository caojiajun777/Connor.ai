"""Run repository and full-state reconstruction."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import literal, select, union_all
from sqlalchemy.orm import Session

from app.db.models import RunRecord
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
    RunState,
    ThreadStatus,
    ToolCallRecord,
    TraceEvent,
    WatchlistItem,
)
from app.repositories.base import DomainRepository, enum_value
from app.repositories.domain import (
    ArchivedSignalRepository,
    ArtifactRepository,
    CandidateRepository,
    DailyReportRepository,
    EvaluationRepository,
    EvidenceRepository,
    EventClusterRepository,
    IntelligenceThreadRepository,
    ModelCallRepository,
    ReviewIssueRepository,
    ReviewResultRepository,
    ToolCallRepository,
    TraceEventRepository,
    WatchlistRepository,
)


@dataclass(frozen=True)
class FullRunState:
    """A reconstructed run with all persisted child records."""

    run: RunState
    evidence: list[EvidenceItem]
    candidates: list[CandidateItem]
    clusters: list[EventCluster]
    evaluations: list[EvaluationResult]
    watchlist: list[WatchlistItem]
    archives: list[ArchivedSignal]
    threads: list[IntelligenceThread]
    reports: list[DailyReport]
    trace_events: list[TraceEvent]
    tool_calls: list[ToolCallRecord]
    model_calls: list[ModelCallRecord]
    artifacts: list[Artifact]
    review_results: list[ReviewResult]
    review_issues: list[ReviewIssue]


class RunRepository(DomainRepository[RunState, RunRecord]):
    domain_model = RunState
    record_model = RunRecord
    warn_on_payload_merge = False

    def __init__(self, session: Session):
        super().__init__(session)
        self.evidence = EvidenceRepository(session)
        self.candidates = CandidateRepository(session)
        self.clusters = EventClusterRepository(session)
        self.evaluations = EvaluationRepository(session)
        self.watchlist = WatchlistRepository(session)
        self.archives = ArchivedSignalRepository(session)
        self.threads = IntelligenceThreadRepository(session)
        self.reports = DailyReportRepository(session)
        self.traces = TraceEventRepository(session)
        self.tool_calls = ToolCallRepository(session)
        self.model_calls = ModelCallRepository(session)
        self.artifacts = ArtifactRepository(session)
        self.review_results = ReviewResultRepository(session)
        self.review_issues = ReviewIssueRepository(session)

    def to_record(self, obj: RunState) -> RunRecord:
        return RunRecord(
            **self._common_values(obj),
            report_date=obj.report_date,
            objective=obj.objective,
            phase=enum_value(obj.phase),
            status=enum_value(obj.status),
            error_summary=obj.error_summary,
        )

    def get_full_state(self, run_id: str) -> FullRunState:
        run = self.require(run_id)
        child_payloads = self._list_run_child_payloads(run_id)
        active_thread_statuses = [
            ThreadStatus.ACTIVE.value,
            ThreadStatus.DORMANT.value,
            ThreadStatus.ARCHIVED.value,
            ThreadStatus.RESOLVED.value,
        ]
        # Threads are cross-run entities by design — they connect signals
        # across multiple daily runs and are not scoped to a single run_id.
        # The dashboard expects global thread visibility.
        threads = self.threads.list_by_statuses(active_thread_statuses)
        return FullRunState(
            run=run,
            evidence=self._hydrate_child(child_payloads, "evidence", EvidenceItem),
            candidates=self._hydrate_child(child_payloads, "candidates", CandidateItem),
            clusters=self._hydrate_child(child_payloads, "clusters", EventCluster),
            evaluations=self._hydrate_child(child_payloads, "evaluations", EvaluationResult),
            watchlist=self._hydrate_child(child_payloads, "watchlist", WatchlistItem),
            archives=self._hydrate_child(child_payloads, "archives", ArchivedSignal),
            threads=threads,
            reports=self._hydrate_child(child_payloads, "reports", DailyReport),
            trace_events=self._hydrate_child(child_payloads, "trace_events", TraceEvent),
            tool_calls=self._hydrate_child(child_payloads, "tool_calls", ToolCallRecord),
            model_calls=self._hydrate_child(child_payloads, "model_calls", ModelCallRecord),
            artifacts=self._hydrate_child(child_payloads, "artifacts", Artifact),
            review_results=self._hydrate_child(child_payloads, "review_results", ReviewResult),
            review_issues=self._hydrate_child(child_payloads, "review_issues", ReviewIssue),
        )

    def _list_run_child_payloads(self, run_id: str) -> dict[str, list[dict[str, Any]]]:
        repositories = {
            "evidence": self.evidence,
            "candidates": self.candidates,
            "clusters": self.clusters,
            "evaluations": self.evaluations,
            "watchlist": self.watchlist,
            "archives": self.archives,
            "reports": self.reports,
            "trace_events": self.traces,
            "tool_calls": self.tool_calls,
            "model_calls": self.model_calls,
            "artifacts": self.artifacts,
            "review_results": self.review_results,
            "review_issues": self.review_issues,
        }
        statements = [
            select(
                literal(name).label("collection"),
                repository.record_model.payload.label("payload"),
            ).where(repository.record_model.run_id == run_id)
            for name, repository in repositories.items()
        ]
        rows = self.session.execute(union_all(*statements)).all()
        payloads = {name: [] for name in repositories}
        for collection, payload in rows:
            payloads[collection].append(payload)
        return payloads

    @staticmethod
    def _hydrate_child(payloads: dict[str, list[dict[str, Any]]], name: str, model):
        objects = [model.model_validate(payload) for payload in payloads[name]]
        if name == "trace_events":
            return sorted(objects, key=lambda item: item.seq)
        return sorted(objects, key=lambda item: item.created_at)
