"""Helpers for harness tests."""

from __future__ import annotations

from datetime import timedelta
from app.agents import AgentRunRequest, AgentRunResult
from app.agents.outputs import EditorOutput, ReviewerOutput, WriterOutput
from app.domain import (
    AgentRole,
    DailyReport,
    ReviewDecision,
    ReviewIssue,
    ReviewResult,
    RunPhase,
    ReportStatus,
    TraceEvent,
    TraceEventType,
    TraceStatus,
)
from app.harness import AgentTask
from app.repositories import DailyReportRepository, ReviewIssueRepository, ReviewResultRepository
from tests.domain.fixtures import BASE_TIME, RUN_ID, daily_report_fixture


def persist_bundle(db_session, bundle: dict[str, object]) -> None:
    from app.repositories import (
        CandidateRepository,
        EvaluationRepository,
        EventClusterRepository,
        EvidenceRepository,
    )

    EvidenceRepository(db_session).add_many(bundle.get("evidence", []))
    if bundle.get("candidate") is not None:
        CandidateRepository(db_session).add(bundle["candidate"])
    if bundle.get("cluster") is not None:
        EventClusterRepository(db_session).add(bundle["cluster"])
    if bundle.get("evaluation") is not None:
        EvaluationRepository(db_session).add(bundle["evaluation"])


class ScriptedWritingAgentRunner:
    """Test double that simulates AgentScope writer/reviewer/editor side effects."""

    def __init__(self, db_session):
        self.db_session = db_session
        self.calls: list[AgentRunRequest] = []
        self.review_calls = 0

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.calls.append(request)
        if request.agent_role == AgentRole.WRITER:
            report = self._create_report()
            return self._result(
                request,
                WriterOutput(
                    summary="Writer created draft report.",
                    report_ids=[report.id],
                    markdown_preview=report.full_markdown,
                ),
            )

        if request.agent_role == AgentRole.REVIEWER:
            self.review_calls += 1
            if request.phase == RunPhase.FINAL_REVIEW or self.review_calls > 1:
                review = self._create_pass_review()
                output = ReviewerOutput(
                    summary="Reviewer passed final report.",
                    decision=ReviewDecision.PASS,
                    review_result_ids=[review.id],
                )
            else:
                review = self._create_revise_review()
                output = ReviewerOutput(
                    summary="Reviewer requested revision.",
                    decision=ReviewDecision.REVISE,
                    review_result_ids=[review.id],
                    required_changes=review.required_changes,
                )
            return self._result(request, output)

        if request.agent_role == AgentRole.EDITOR:
            report = DailyReportRepository(self.db_session).require("report_harness")
            edited = report.model_copy(
                update={
                    "metadata": {**report.metadata, "edited": True},
                    "updated_at": BASE_TIME + timedelta(minutes=3),
                }
            )
            DailyReportRepository(self.db_session).add(edited)
            return self._result(
                request,
                EditorOutput(
                    summary="Editor revised report.",
                    edited_report_ids=[edited.id],
                ),
            )

        raise AssertionError(f"unexpected agent role: {request.agent_role}")

    def _create_report(self) -> DailyReport:
        report = daily_report_fixture().model_copy(
            update={
                "id": "report_harness",
                "run_id": RUN_ID,
                "status": ReportStatus.DRAFT,
                "review_result_ids": [],
                "trace_timeline_ids": [],
                "created_at": BASE_TIME + timedelta(minutes=1),
                "updated_at": None,
            }
        )
        DailyReportRepository(self.db_session).add(report)
        return report

    def _create_revise_review(self) -> ReviewResult:
        issue = ReviewIssue(
            id="issue_harness_revision",
            run_id=RUN_ID,
            report_id="report_harness",
            priority=1,
            title="Clarify early signal uncertainty",
            body="The draft needs a stronger uncertainty label.",
            created_at=BASE_TIME + timedelta(minutes=2),
        )
        ReviewIssueRepository(self.db_session).add(issue)
        review = ReviewResult(
            id="review_harness_revise",
            run_id=RUN_ID,
            report_id="report_harness",
            decision=ReviewDecision.REVISE,
            issues=[issue],
            required_changes=["Clarify early signal uncertainty"],
            reasoning_summary="Uncertainty needs to be more explicit.",
            created_at=BASE_TIME + timedelta(minutes=2),
        )
        ReviewResultRepository(self.db_session).add(review)
        return review

    def _create_pass_review(self) -> ReviewResult:
        review = ReviewResult(
            id="review_harness_pass",
            run_id=RUN_ID,
            report_id="report_harness",
            decision=ReviewDecision.PASS,
            reasoning_summary="Report now passes quality checks.",
            created_at=BASE_TIME + timedelta(minutes=4),
        )
        ReviewResultRepository(self.db_session).add(review)
        return review

    @staticmethod
    def _result(request: AgentRunRequest, output) -> AgentRunResult:
        return AgentRunResult(
            run_id=request.run_id,
            phase=request.phase,
            agent_role=request.agent_role,
            structured_output=output,
            start_trace_event=TraceEvent(
                id=f"trace_{request.agent_role.value}_{request.phase.value}_start",
                run_id=request.run_id,
                seq=0,
                phase=request.phase,
                agent_role=request.agent_role,
                event_type=TraceEventType.AGENT_STARTED,
                status=TraceStatus.STARTED,
                summary="scripted start",
                created_at=BASE_TIME,
            ),
        )


def writing_tasks() -> dict[RunPhase, list[AgentTask]]:
    return {
        RunPhase.WRITING: [
            AgentTask(
                agent_role=AgentRole.WRITER,
                phase=RunPhase.WRITING,
                task="Draft daily report.",
            )
        ],
        RunPhase.REVIEWING: [
            AgentTask(
                agent_role=AgentRole.REVIEWER,
                phase=RunPhase.REVIEWING,
                task="Review daily report.",
            )
        ],
        RunPhase.EDITING: [
            AgentTask(
                agent_role=AgentRole.EDITOR,
                phase=RunPhase.EDITING,
                task="Revise daily report.",
            )
        ],
        RunPhase.FINAL_REVIEW: [
            AgentTask(
                agent_role=AgentRole.REVIEWER,
                phase=RunPhase.FINAL_REVIEW,
                task="Final review daily report.",
            )
        ],
    }
