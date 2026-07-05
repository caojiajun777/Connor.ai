"""Writing output materialization tests."""

from app.agents.outputs import (
    EditorOutput,
    ReportDraft,
    ReportItemDraft,
    ReportSectionDraft,
    ReviewDraft,
    ReviewerOutput,
    WriterOutput,
)
from app.agents.schemas import AgentRunResult
from app.domain import AgentRole, ReportStatus, ReviewDecision, RunPhase, TraceEventType
from app.harness import HarnessContext
from app.repositories import (
    CandidateRepository,
    DailyReportRepository,
    EvaluationRepository,
    EventClusterRepository,
    EvidenceRepository,
    ReviewResultRepository,
    RunRepository,
)
from app.services import TraceService
from app.writing import WritingOutputMaterializer
from tests.domain.fixtures import early_signal_bundle, run_state_fixture


def test_writer_output_materializer_creates_report_artifacts(db_session) -> None:
    run = _persist_run_and_bundle(db_session)
    output = WriterOutput(
        summary="Writer drafted report.",
        report_drafts=[_report_draft(status_label="Unconfirmed gray rollout feedback")],
    )

    result = WritingOutputMaterializer(HarnessContext(db_session)).materialize(
        run=run,
        phase=RunPhase.WRITING,
        agent_role=AgentRole.WRITER,
        result=_agent_result(run.id, RunPhase.WRITING, AgentRole.WRITER, output),
    )

    assert result.report_ids
    report = DailyReportRepository(db_session).require(result.report_ids[0])
    assert report.status == ReportStatus.DRAFT
    assert report.full_markdown.startswith("# Connor.ai Daily Intelligence")
    assert report.full_json["sections"][0]["section_id"] == "early_signals"
    assert report.evidence_map[0].evidence_ids == ["ev_openai_hn_reasoning", "ev_openai_wrapper_commit"]
    assert report.trace_timeline_ids
    assert RunRepository(db_session).require(run.id).report_id == report.id

    timeline = TraceService(db_session).reconstruct_timeline(run.id)
    assert TraceEventType.REPORT_DRAFTED in [event.event_type for event in timeline.events]


def test_writer_materializer_normalizes_item_category_to_cluster_category(db_session) -> None:
    run = _persist_run_and_bundle(db_session)
    output = WriterOutput(
        summary="Writer drafted report with mismatched category.",
        report_drafts=[
            _report_draft(
                status_label="Unconfirmed gray rollout feedback",
                category="research",
            )
        ],
    )

    result = WritingOutputMaterializer(HarnessContext(db_session)).materialize(
        run=run,
        phase=RunPhase.WRITING,
        agent_role=AgentRole.WRITER,
        result=_agent_result(run.id, RunPhase.WRITING, AgentRole.WRITER, output),
    )

    report = DailyReportRepository(db_session).require(result.report_ids[0])
    assert report.sections[0].items[0].category == "early_signal"


def test_writer_materializer_normalizes_watchlist_update_shape(db_session) -> None:
    run = _persist_run_and_bundle(db_session)
    output = WriterOutput(
        summary="Writer drafted report with watchlist-item shaped updates.",
        report_drafts=[
            _report_draft(
                status_label="Unconfirmed gray rollout feedback",
                watchlist_updates=[
                    {
                        "watchlist_id": "watch_openai_reasoning",
                        "status": "active",
                        "priority": "high",
                        "title": "OpenAI reasoning-control API watch",
                        "thesis": "Community and code signals still need official confirmation.",
                        "open_questions": ["Check OpenAI changelog."],
                        "evidence_ids": [
                            "ev_openai_hn_reasoning",
                            "ev_openai_wrapper_commit",
                        ],
                    }
                ],
            )
        ],
    )

    result = WritingOutputMaterializer(HarnessContext(db_session)).materialize(
        run=run,
        phase=RunPhase.WRITING,
        agent_role=AgentRole.WRITER,
        result=_agent_result(run.id, RunPhase.WRITING, AgentRole.WRITER, output),
    )

    report = DailyReportRepository(db_session).require(result.report_ids[0])
    update = report.watchlist_updates[0]
    assert update.watchlist_id == "watch_openai_reasoning"
    assert update.topic == "OpenAI reasoning-control API watch"
    assert update.current_status == "active"
    assert update.new_developments == [
        "Community and code signals still need official confirmation."
    ]
    assert update.next_watch == ["Check OpenAI changelog."]

    timeline = TraceService(db_session).reconstruct_timeline(run.id)
    assert any(
        event.metadata.get("normalized_count") == 1
        for event in timeline.events
        if event.event_type == TraceEventType.AGENT_DECISION
    )


def test_reviewer_materializer_blocks_early_signal_fact_language(db_session) -> None:
    run = _persist_run_and_bundle(db_session)
    context = HarnessContext(db_session)
    materializer = WritingOutputMaterializer(context)
    materializer.materialize(
        run=run,
        phase=RunPhase.WRITING,
        agent_role=AgentRole.WRITER,
        result=_agent_result(
            run.id,
            RunPhase.WRITING,
            AgentRole.WRITER,
            WriterOutput(
                summary="Writer drafted bad report.",
                report_drafts=[_report_draft(status_label="Confirmed official launch")],
            ),
        ),
    )
    report = DailyReportRepository(db_session).list_by_run(run.id)[0]

    result = materializer.materialize(
        run=run,
        phase=RunPhase.REVIEWING,
        agent_role=AgentRole.REVIEWER,
        result=_agent_result(
            run.id,
            RunPhase.REVIEWING,
            AgentRole.REVIEWER,
            ReviewerOutput(
                summary="Reviewer passed report.",
                decision=ReviewDecision.PASS,
                review_drafts=[
                    ReviewDraft(
                        report_id=report.id,
                        decision=ReviewDecision.PASS,
                        reasoning_summary="Looks good.",
                    )
                ],
            ),
        ),
    )

    review = ReviewResultRepository(db_session).require(result.review_result_ids[0])
    updated_report = DailyReportRepository(db_session).require(report.id)
    assert review.decision == ReviewDecision.REVISE
    assert review.issues[0].title == "Early signal is written with confirmed-fact language"
    assert updated_report.status == ReportStatus.NEEDS_REVISION


def test_reviewer_guard_checks_core_language_independently(db_session) -> None:
    run = _persist_run_and_bundle(db_session)
    context = HarnessContext(db_session)
    materializer = WritingOutputMaterializer(context)
    materializer.materialize(
        run=run,
        phase=RunPhase.WRITING,
        agent_role=AgentRole.WRITER,
        result=_agent_result(
            run.id,
            RunPhase.WRITING,
            AgentRole.WRITER,
            WriterOutput(
                summary="Writer drafted internally inconsistent report.",
                report_drafts=[
                    _report_draft(
                        status_label="Unconfirmed gray rollout feedback",
                        core_information="OpenAI has launched a new reasoning-control option.",
                    )
                ],
            ),
        ),
    )
    report = DailyReportRepository(db_session).list_by_run(run.id)[0]

    result = materializer.materialize(
        run=run,
        phase=RunPhase.REVIEWING,
        agent_role=AgentRole.REVIEWER,
        result=_agent_result(
            run.id,
            RunPhase.REVIEWING,
            AgentRole.REVIEWER,
            ReviewerOutput(
                summary="Reviewer passed report.",
                decision=ReviewDecision.PASS,
                review_drafts=[
                    ReviewDraft(
                        report_id=report.id,
                        decision=ReviewDecision.PASS,
                        reasoning_summary="Looks good.",
                    )
                ],
            ),
        ),
    )

    review = ReviewResultRepository(db_session).require(result.review_result_ids[0])
    assert review.decision == ReviewDecision.REVISE


def test_editor_output_materializer_updates_existing_report(db_session) -> None:
    run = _persist_run_and_bundle(db_session)
    context = HarnessContext(db_session)
    materializer = WritingOutputMaterializer(context)
    materializer.materialize(
        run=run,
        phase=RunPhase.WRITING,
        agent_role=AgentRole.WRITER,
        result=_agent_result(
            run.id,
            RunPhase.WRITING,
            AgentRole.WRITER,
            WriterOutput(
                summary="Writer drafted report.",
                report_drafts=[_report_draft(status_label="Confirmed official launch")],
            ),
        ),
    )
    report = DailyReportRepository(db_session).list_by_run(run.id)[0]

    result = materializer.materialize(
        run=run,
        phase=RunPhase.EDITING,
        agent_role=AgentRole.EDITOR,
        result=_agent_result(
            run.id,
            RunPhase.EDITING,
            AgentRole.EDITOR,
            EditorOutput(
                summary="Editor revised report.",
                revised_report_drafts=[
                    _report_draft(
                        report_id=report.id,
                        status_label="Unconfirmed gray rollout feedback",
                    )
                ],
            ),
        ),
    )

    edited = DailyReportRepository(db_session).require(report.id)
    assert result.report_ids == [report.id]
    assert edited.updated_at is not None
    assert edited.sections[0].items[0].status_label == "Unconfirmed gray rollout feedback"
    assert "Unconfirmed gray rollout feedback" in edited.full_markdown

    timeline = TraceService(db_session).reconstruct_timeline(run.id)
    assert TraceEventType.REPORT_EDITED in [event.event_type for event in timeline.events]


def _persist_run_and_bundle(db_session):
    run = run_state_fixture().model_copy(update={"phase": RunPhase.WRITING})
    RunRepository(db_session).add(run)
    bundle = early_signal_bundle()
    EvidenceRepository(db_session).add_many(bundle["evidence"])
    CandidateRepository(db_session).add(bundle["candidate"])
    EventClusterRepository(db_session).add(bundle["cluster"])
    EvaluationRepository(db_session).add(bundle["evaluation"])
    db_session.flush()
    return run


def _report_draft(
    *,
    status_label: str,
    report_id: str | None = None,
    category: str = "early_signal",
    core_information: str = (
        "Community discussion and third-party code suggest a possible "
        "new reasoning-control option."
    ),
    watchlist_updates: list[dict] | None = None,
) -> ReportDraft:
    return ReportDraft(
        report_id=report_id,
        overview_judgments=["Early API-surface signal is specific but unconfirmed."],
        tomorrow_focus=["Check official changelog and SDK commits."],
        watchlist_updates=watchlist_updates or [],
        sections=[
            ReportSectionDraft(
                section_id="early_signals",
                title="前沿爆料 Early Signals",
                items=[
                    ReportItemDraft(
                        title="OpenAI suspected reasoning-control API test",
                        category=category,
                        status_label=status_label,
                        core_information=core_information,
                        why_it_matters=(
                            "It may affect how developers tune cost, latency, and reasoning depth."
                        ),
                        potential_impact=(
                            "If confirmed, agent frameworks may expose finer reasoning controls."
                        ),
                        evidence_ids=["ev_openai_hn_reasoning", "ev_openai_wrapper_commit"],
                        cluster_ids=["cl_openai_reasoning_api"],
                        followup_points=["Check official docs and first-party SDK commits."],
                        uncertainty_label="low confidence, high trackability",
                    )
                ],
            )
        ],
    )


def _agent_result(run_id, phase, agent_role, output) -> AgentRunResult:
    return AgentRunResult(
        run_id=run_id,
        phase=phase,
        agent_role=agent_role,
        structured_output=output,
    )
