"""Run repository and full-state reconstruction."""

from dataclasses import dataclass

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
        return FullRunState(
            run=run,
            evidence=self.evidence.list_by_run(run_id),
            candidates=self.candidates.list_by_run(run_id),
            clusters=self.clusters.list_by_run(run_id),
            evaluations=self.evaluations.list_by_run(run_id),
            watchlist=self.watchlist.list_by_run(run_id),
            archives=self.archives.list_by_run(run_id),
            threads=self.threads.list_by_status("active")
            + self.threads.list_by_status("dormant")
            + self.threads.list_by_status("archived")
            + self.threads.list_by_status("resolved"),
            reports=self.reports.list_by_run(run_id),
            trace_events=self.traces.list_timeline(run_id),
            tool_calls=self.tool_calls.list_by_run(run_id),
            model_calls=self.model_calls.list_by_run(run_id),
            artifacts=self.artifacts.list_by_run(run_id),
            review_results=self.review_results.list_by_run(run_id),
            review_issues=self.review_issues.list_by_run(run_id),
        )

