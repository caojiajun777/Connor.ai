"""Writing loop harness tests."""

from app.agents.outputs import (
    EditorOutput,
    ReportDraft,
    ReportItemDraft,
    ReportSectionDraft,
    ReviewDraft,
    ReviewerOutput,
    WriterOutput,
)
from app.agents.schemas import AgentRunRequest, AgentRunResult
from app.domain import AgentRole, ReviewDecision, RunPhase, TraceEventType
from app.harness import HarnessConfig, HarnessContext, WritingGateOutcome, WritingLoopHarness
from app.repositories import DailyReportRepository, RunRepository
from app.services import TraceService
from tests.domain.fixtures import RUN_ID, early_signal_bundle, run_state_fixture
from tests.harness.helpers import ScriptedWritingAgentRunner, persist_bundle, writing_tasks


def test_writing_loop_revises_then_finalizes(db_session) -> None:
    run = run_state_fixture().model_copy(
        update={
            "phase": RunPhase.WRITING,
            "selected_cluster_ids": ["cl_openai_reasoning_api"],
        }
    )
    RunRepository(db_session).add(run)
    persist_bundle(db_session, early_signal_bundle())
    agent_runner = ScriptedWritingAgentRunner(db_session)
    context = HarnessContext(
        db_session,
        agent_runner=agent_runner,
        config=HarnessConfig(max_writing_revisions=2, min_report_body_items=1),
    )

    next_run, decisions = WritingLoopHarness(context).run(run, tasks_by_phase=writing_tasks())

    assert next_run.status == "completed"
    assert next_run.phase == "finalized"
    assert next_run.report_id == "report_harness"
    assert [decision.outcome for decision in decisions] == [
        WritingGateOutcome.REVISE,
        WritingGateOutcome.FINALIZE,
    ]
    assert DailyReportRepository(db_session).require("report_harness").status == "final"
    assert [call.agent_role for call in agent_runner.calls] == [
        "writer",
        "reviewer",
        "editor",
        "reviewer",
    ]


def test_writing_loop_materializes_agent_drafts_end_to_end(db_session) -> None:
    run = run_state_fixture().model_copy(
        update={
            "phase": RunPhase.WRITING,
            "selected_cluster_ids": ["cl_openai_reasoning_api"],
        }
    )
    RunRepository(db_session).add(run)
    persist_bundle(db_session, early_signal_bundle())
    agent_runner = DraftOnlyWritingAgentRunner()
    context = HarnessContext(
        db_session,
        agent_runner=agent_runner,
        config=HarnessConfig(max_writing_revisions=2, min_report_body_items=1),
    )

    next_run, decisions = WritingLoopHarness(context).run(run, tasks_by_phase=writing_tasks())

    assert next_run.status == "completed"
    assert next_run.phase == "finalized"
    assert [decision.outcome for decision in decisions] == [
        WritingGateOutcome.REVISE,
        WritingGateOutcome.FINALIZE,
    ]

    report = DailyReportRepository(db_session).require(next_run.report_id)
    assert report.status == "final"
    assert report.full_json["sections"][0]["section_id"] == "early_signals"
    assert report.evidence_map
    assert report.trace_timeline_ids
    assert agent_runner.final_review_status_label == "Unconfirmed gray rollout feedback"

    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)
    event_types = [event.event_type for event in timeline.events]
    assert TraceEventType.REPORT_DRAFTED in event_types
    assert TraceEventType.REVIEW_COMPLETED in event_types
    assert TraceEventType.REPORT_EDITED in event_types
    assert TraceEventType.REPORT_FINALIZED in event_types
    assert any(
        event.summary == "Harness dispatching writer writing task."
        and event.metadata["task_progress"] is True
        for event in timeline.events
    )
    assert any(
        event.summary == "Harness completed reviewer writing task."
        and event.metadata["duration_ms"] >= 0
        for event in timeline.events
    )

    assert [call.agent_role for call in agent_runner.calls] == [
        "writer",
        "reviewer",
        "editor",
        "reviewer",
    ]


class DraftOnlyWritingAgentRunner:
    """Runner that returns structured drafts and performs no repository writes."""

    def __init__(self):
        self.calls: list[AgentRunRequest] = []
        self.review_calls = 0
        self.final_review_status_label: str | None = None

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.calls.append(request)
        if request.agent_role == AgentRole.WRITER:
            output = WriterOutput(
                summary="Writer returned report draft.",
                report_drafts=[_report_draft(status_label="Confirmed official launch")],
            )
            return _agent_result(request, output)

        if request.agent_role == AgentRole.REVIEWER:
            self.review_calls += 1
            if request.phase == RunPhase.FINAL_REVIEW or self.review_calls > 1:
                self.final_review_status_label = request.context["review_context"]["report"][
                    "sections"
                ][0]["items"][0]["status_label"]
                output = ReviewerOutput(
                    summary="Reviewer passed revised report.",
                    decision=ReviewDecision.PASS,
                    review_drafts=[
                        ReviewDraft(
                            decision=ReviewDecision.PASS,
                            reasoning_summary="Report now keeps uncertainty boundaries.",
                        )
                    ],
                )
            else:
                output = ReviewerOutput(
                    summary="Reviewer requested revision.",
                    decision=ReviewDecision.REVISE,
                    required_changes=["Remove confirmed-fact language from early signal."],
                    review_drafts=[
                        ReviewDraft(
                            decision=ReviewDecision.REVISE,
                            required_changes=[
                                "Remove confirmed-fact language from early signal."
                            ],
                            reasoning_summary="Early signal wording is too certain.",
                        )
                    ],
                )
            return _agent_result(request, output)

        if request.agent_role == AgentRole.EDITOR:
            report_id = request.context["editor_context"]["report"]["id"]
            output = EditorOutput(
                summary="Editor returned revised report draft.",
                revised_report_drafts=[
                    _report_draft(
                        status_label="Unconfirmed gray rollout feedback",
                        report_id=report_id,
                    )
                ],
            )
            return _agent_result(request, output)

        raise AssertionError(f"unexpected agent role: {request.agent_role}")


def _report_draft(status_label: str, report_id: str | None = None) -> ReportDraft:
    return ReportDraft(
        report_id=report_id,
        overview_judgments=["一个具体但未确认的 API surface 信号需要继续追踪。"],
        tomorrow_focus=["检查第一方 changelog 和 SDK commit。"],
        sections=[
            ReportSectionDraft(
                section_id="early_signals",
                title="前沿爆料 Early Signals",
                items=[
                    ReportItemDraft(
                        title="OpenAI suspected reasoning-control API test",
                        category="early_signal",
                        status_label=status_label,
                        core_information=(
                            "社区讨论和第三方代码显示，OpenAI 可能正在测试新的 reasoning-control 选项。"
                        ),
                        why_it_matters=(
                            "这会影响开发者如何在成本、延迟和推理深度之间做权衡。"
                        ),
                        potential_impact=(
                            "如果后续被确认，agent 框架可能会暴露更细的 reasoning 控制能力。"
                        ),
                        evidence_ids=["ev_openai_hn_reasoning", "ev_openai_wrapper_commit"],
                        cluster_ids=["cl_openai_reasoning_api"],
                        followup_points=["检查官方文档和第一方 SDK commit 是否出现同名参数。"],
                        uncertainty_label="低置信度，但可追踪性较高。",
                    )
                ],
            )
        ],
    )


def _agent_result(request: AgentRunRequest, output) -> AgentRunResult:
    return AgentRunResult(
        run_id=request.run_id,
        phase=request.phase,
        agent_role=request.agent_role,
        structured_output=output,
    )
