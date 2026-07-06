"""Writing output materialization tests."""

from app.agents.outputs import (
    EditorOutput,
    ReportDraft,
    ReportItemDraft,
    ReportSectionDraft,
    ReviewDraft,
    ReviewIssueDraft,
    ReviewerOutput,
    WriterOutput,
)
from app.agents.schemas import AgentRunResult
from app.domain import (
    AgentRole,
    CandidateCategory,
    ReportStatus,
    ReviewDecision,
    RunPhase,
    TraceEventType,
)
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
from tests.domain.fixtures import (
    confirmed_event_bundle,
    early_signal_bundle,
    run_state_fixture,
    tech_finance_bundle,
)


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


def test_writer_materializer_repairs_tech_finance_tickers_from_cluster(db_session) -> None:
    run = _persist_run_and_bundle(db_session)
    finance = tech_finance_bundle()
    EvidenceRepository(db_session).add_many(finance["evidence"])
    CandidateRepository(db_session).add(finance["candidate"])
    EventClusterRepository(db_session).add(finance["cluster"])
    EvaluationRepository(db_session).add(finance["evaluation"])
    output = WriterOutput(
        summary="Writer drafted finance report with missing finance fields.",
        report_drafts=[
            _report_draft(
                status_label="Needs market follow-up",
                category="other",
                potential_impact=None,
                evidence_ids=[finance["evidence"][0].id],
                cluster_ids=[finance["cluster"].id],
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
    item = report.sections[0].items[0]
    assert item.category == CandidateCategory.TECH_FINANCE
    assert item.tickers == ["NVDA", "TSM"]
    assert item.potential_impact
    assert "Impact chain:" in item.potential_impact


def test_writer_materializer_repairs_tech_finance_impact_from_cluster_claim(db_session) -> None:
    run = _persist_run_and_bundle(db_session)
    finance = tech_finance_bundle()
    cluster = finance["cluster"].model_copy(update={"tickers": []})
    EvidenceRepository(db_session).add_many(finance["evidence"])
    CandidateRepository(db_session).add(finance["candidate"])
    EventClusterRepository(db_session).add(cluster)
    EvaluationRepository(db_session).add(finance["evaluation"])
    output = WriterOutput(
        summary="Writer drafted finance report with no ticker lineage.",
        report_drafts=[
            _report_draft(
                status_label="Needs market follow-up",
                category="other",
                potential_impact=None,
                evidence_ids=[finance["evidence"][0].id],
                cluster_ids=[cluster.id],
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
    item = report.sections[0].items[0]
    assert item.category == CandidateCategory.TECH_FINANCE
    assert item.tickers == []
    assert item.potential_impact
    assert item.potential_impact.startswith("Tech-finance impact requires follow-up")


def test_writer_materializer_narrows_mixed_category_item_lineage(db_session) -> None:
    run = _persist_run_and_bundle(db_session)
    finance = tech_finance_bundle()
    EvidenceRepository(db_session).add_many(finance["evidence"])
    CandidateRepository(db_session).add(finance["candidate"])
    EventClusterRepository(db_session).add(finance["cluster"])
    EvaluationRepository(db_session).add(finance["evaluation"])
    output = WriterOutput(
        summary="Writer drafted one mixed-category item.",
        report_drafts=[
            _report_draft(
                status_label="Mixed follow-up item",
                category="other",
                evidence_ids=[
                    "ev_openai_hn_reasoning",
                    finance["evidence"][0].id,
                ],
                cluster_ids=[
                    "cl_openai_reasoning_api",
                    finance["cluster"].id,
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
    item = report.sections[0].items[0]
    assert item.category == CandidateCategory.EARLY_SIGNAL
    assert item.cluster_ids == ["cl_openai_reasoning_api"]
    assert item.evidence_ids == ["ev_openai_hn_reasoning"]


def test_writer_materializer_hedges_uncertain_item_language(db_session) -> None:
    run = _persist_run_and_bundle(db_session)
    output = WriterOutput(
        summary="Writer drafted overconfident early signal.",
        report_drafts=[
            _report_draft(
                status_label="Observed model behavior",
                key_data=["Evasion rate >=65% across several models"],
                potential_impact="Medium to High if adopted by agent frameworks.",
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
    item = report.sections[0].items[0]
    assert item.status_label.startswith("Preliminary / unconfirmed")
    assert not item.core_information.startswith("Preliminary signal")
    assert item.key_data == [
        "Preprint claim (unvalidated): Evasion rate >=65% across several models"
    ]
    assert item.potential_impact
    assert item.potential_impact.startswith("Low to Medium (preprint, unvalidated)")
    assert any("peer review status" in point for point in item.followup_points)


def test_writer_materializer_repairs_missing_followups_and_emoji(db_session) -> None:
    run = _persist_run_and_bundle(db_session)
    output = WriterOutput(
        summary="Writer drafted item with formatting issues.",
        report_drafts=[
            _report_draft(
                status_label="Unconfirmed gray rollout feedback",
                core_information="🤗 Kernels may have a relevant update.",
                followup_points=[],
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
    item = report.sections[0].items[0]
    assert "🤗" not in item.core_information
    assert "Hugging Face" in item.core_information
    assert item.followup_points


def test_writer_materializer_derives_tomorrow_focus_from_section(db_session) -> None:
    run = _persist_run_and_bundle(db_session)
    draft = _report_draft(
        status_label="Unconfirmed gray rollout feedback",
        tomorrow_focus=[],
    )
    tomorrow_item = ReportItemDraft(
        title="Tomorrow priority",
        category="early_signal",
        status_label="Unconfirmed follow-up",
        core_information="Check whether official docs confirm the signal.",
        why_it_matters="It determines whether the signal should be upgraded.",
        evidence_ids=["ev_openai_hn_reasoning"],
        cluster_ids=["cl_openai_reasoning_api"],
        followup_points=["Check official API changelog tomorrow."],
        uncertainty_label="unconfirmed",
    )
    draft = draft.model_copy(
        update={
            "sections": [
                *draft.sections,
                ReportSectionDraft(
                    section_id="tomorrow_focus",
                    title="Tomorrow Focus",
                    items=[tomorrow_item],
                ),
            ]
        }
    )
    output = WriterOutput(summary="Writer drafted report.", report_drafts=[draft])

    result = WritingOutputMaterializer(HarnessContext(db_session)).materialize(
        run=run,
        phase=RunPhase.WRITING,
        agent_role=AgentRole.WRITER,
        result=_agent_result(run.id, RunPhase.WRITING, AgentRole.WRITER, output),
    )

    report = DailyReportRepository(db_session).require(result.report_ids[0])
    assert "Check official API changelog tomorrow." in report.full_json["tomorrow_focus"]


def test_writer_materializer_normalizes_section_order_and_markdown(db_session) -> None:
    run = _persist_run_and_bundle(db_session)
    official = confirmed_event_bundle()
    finance = tech_finance_bundle()
    EvidenceRepository(db_session).add_many(official["evidence"])
    EvidenceRepository(db_session).add_many(finance["evidence"])
    CandidateRepository(db_session).add(official["candidate"])
    CandidateRepository(db_session).add(finance["candidate"])
    EventClusterRepository(db_session).add(official["cluster"])
    EventClusterRepository(db_session).add(finance["cluster"])
    EvaluationRepository(db_session).add(official["evaluation"])
    EvaluationRepository(db_session).add(finance["evaluation"])

    early_section = _report_draft(
        status_label="Unconfirmed gray rollout feedback",
    ).sections[0]
    confirmed_item = ReportItemDraft(
        title="Official model update",
        category="official_update",
        status_label="Confirmed official update",
        core_information="The official source published a confirmed product update.",
        why_it_matters="Official updates change the confirmed-events section.",
        evidence_ids=[official["evidence"][0].id],
        cluster_ids=[official["cluster"].id],
        followup_points=["Check official release notes for follow-up metrics."],
    )
    finance_item = ReportItemDraft(
        title="AI infrastructure finance signal",
        category="tech_finance",
        status_label="Investor-relations sourced signal",
        core_information="A finance source points to AI infrastructure demand.",
        why_it_matters="The signal can affect semiconductor supply-chain expectations.",
        potential_impact="Relevant to AI capex expectations.",
        tickers=["NVDA"],
        evidence_ids=[finance["evidence"][0].id],
        cluster_ids=[finance["cluster"].id],
        followup_points=["Check the next filing for confirmed numbers."],
    )
    draft = ReportDraft(
        full_markdown="# Bad model markdown\n\n## 1. Watchlist\n- duplicate",
        overview_judgments=["Selected clusters cover the core report buckets."],
        tomorrow_focus=["Check official sources tomorrow."],
        sections=[
            ReportSectionDraft(
                section_id="finance_first",
                title="Finance First",
                items=[finance_item],
            ),
            ReportSectionDraft(
                section_id="confirmed_second",
                title="Confirmed Second",
                items=[confirmed_item],
            ),
            early_section,
        ],
    )
    output = WriterOutput(summary="Writer drafted unordered report.", report_drafts=[draft])

    result = WritingOutputMaterializer(HarnessContext(db_session)).materialize(
        run=run,
        phase=RunPhase.WRITING,
        agent_role=AgentRole.WRITER,
        result=_agent_result(run.id, RunPhase.WRITING, AgentRole.WRITER, output),
    )

    report = DailyReportRepository(db_session).require(result.report_ids[0])
    assert [section.section_id for section in report.sections] == [
        "early_signals",
        "confirmed_events",
        "tech_finance",
    ]
    assert "# Bad model markdown" not in report.full_markdown
    assert "## 1. 前沿爆料 Early Signals" in report.full_markdown
    assert "## 2. 重大事件确认 Confirmed Events" in report.full_markdown
    assert "## 3. 科技圈金融信息 Tech-Finance" in report.full_markdown
    assert "## 4. 持续追踪 Watchlist" in report.full_markdown
    assert "## 5. 明日重点关注" in report.full_markdown
    assert report.full_json["sections"][0]["section_id"] == "early_signals"


def test_writer_materializer_renders_watchlist_once(db_session) -> None:
    run = _persist_run_and_bundle(db_session)
    output = WriterOutput(
        summary="Writer drafted watchlist section and update.",
        report_drafts=[
            _report_draft(
                status_label="Active watch",
                category="watchlist_update",
                watchlist_updates=[
                    {
                        "watchlist_id": "watch_openai_reasoning",
                        "topic": "OpenAI reasoning-control API watch",
                        "current_status": "active",
                        "new_developments": ["A related signal remains open."],
                        "next_watch": ["Check official changelog."],
                        "evidence_ids": ["ev_openai_hn_reasoning"],
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
    assert [section.section_id for section in report.sections] == ["watchlist"]
    assert report.full_markdown.count("持续追踪 Watchlist") == 1
    assert report.full_markdown.count("OpenAI suspected reasoning-control API test") == 1
    assert "A related signal remains open." not in report.full_markdown
    assert report.full_json["watchlist_updates"][0]["watchlist_id"] == "watch_openai_reasoning"


def test_writer_materializer_allows_watchlist_item_cluster_lineage(db_session) -> None:
    run = _persist_run_and_bundle(db_session)
    output = WriterOutput(
        summary="Writer drafted watchlist section.",
        report_drafts=[
            _report_draft(
                status_label="Active watch",
                category="watchlist_update",
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
    item = report.sections[0].items[0]
    assert item.category == CandidateCategory.WATCHLIST_UPDATE
    assert item.cluster_ids == ["cl_openai_reasoning_api"]
    assert report.evidence_map[0].cluster_ids == ["cl_openai_reasoning_api"]


def test_writer_materializer_allows_watchlist_item_run_evidence_outside_cited_cluster(
    db_session,
) -> None:
    run = _persist_run_and_bundle(db_session)
    official = confirmed_event_bundle()
    EvidenceRepository(db_session).add_many(official["evidence"])
    CandidateRepository(db_session).add(official["candidate"])
    EventClusterRepository(db_session).add(official["cluster"])
    EvaluationRepository(db_session).add(official["evaluation"])
    output = WriterOutput(
        summary="Writer drafted cross-cluster watchlist section.",
        report_drafts=[
            _report_draft(
                status_label="Active watch",
                category="watchlist_update",
                evidence_ids=[official["evidence"][0].id],
                cluster_ids=["cl_openai_reasoning_api"],
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
    item = report.sections[0].items[0]
    assert item.category == CandidateCategory.WATCHLIST_UPDATE
    assert item.evidence_ids == [official["evidence"][0].id]


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


def test_reviewer_materializer_filters_non_blocking_watchlist_overlap(db_session) -> None:
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
                report_drafts=[_report_draft(status_label="Unconfirmed gray rollout feedback")],
            ),
        ),
    )
    report = DailyReportRepository(db_session).list_by_run(run.id)[0]

    result = materializer.materialize(
        run=run,
        phase=RunPhase.FINAL_REVIEW,
        agent_role=AgentRole.REVIEWER,
        result=_agent_result(
            run.id,
            RunPhase.FINAL_REVIEW,
            AgentRole.REVIEWER,
            ReviewerOutput(
                summary="Reviewer requested non-blocking revision.",
                decision=ReviewDecision.REVISE,
                required_changes=[
                    "Merge or differentiate watchlist item because it cites the same cluster."
                ],
                review_drafts=[
                    ReviewDraft(
                        report_id=report.id,
                        decision=ReviewDecision.REVISE,
                        reasoning_summary="Watchlist overlaps with the body item.",
                        issues=[
                            ReviewIssueDraft(
                                priority=2,
                                title="Duplicate watchlist overlap",
                                body="Watchlist and body item cite the same cluster.",
                            )
                        ],
                    )
                ],
            ),
        ),
    )

    review = ReviewResultRepository(db_session).require(result.review_result_ids[0])
    assert review.decision == ReviewDecision.PASS
    assert review.issues == []
    assert review.metadata["filtered_non_blocking_issue_count"] == 1


def test_reviewer_materializer_filters_redundant_uncertainty_prefix(db_session) -> None:
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
                report_drafts=[_report_draft(status_label="Unconfirmed gray rollout feedback")],
            ),
        ),
    )
    report = DailyReportRepository(db_session).list_by_run(run.id)[0]

    result = materializer.materialize(
        run=run,
        phase=RunPhase.FINAL_REVIEW,
        agent_role=AgentRole.REVIEWER,
        result=_agent_result(
            run.id,
            RunPhase.FINAL_REVIEW,
            AgentRole.REVIEWER,
            ReviewerOutput(
                summary="Reviewer requested copy-edit revision.",
                decision=ReviewDecision.REVISE,
                required_changes=[
                    "Remove redundant 'Preliminary signal, not independently validated:' from core_information."
                ],
                review_drafts=[
                    ReviewDraft(
                        report_id=report.id,
                        decision=ReviewDecision.REVISE,
                        reasoning_summary="Only redundant uncertainty wording remains.",
                        issues=[
                            ReviewIssueDraft(
                                priority=1,
                                title="Redundant uncertainty text",
                                body=(
                                    "The phrase 'Preliminary signal, not independently "
                                    "validated' is redundant with the status label."
                                ),
                            )
                        ],
                    )
                ],
            ),
        ),
    )

    review = ReviewResultRepository(db_session).require(result.review_result_ids[0])
    assert review.decision == ReviewDecision.PASS
    assert review.issues == []
    assert review.required_changes == []


def test_reviewer_materializer_falls_back_from_missing_report_id(db_session) -> None:
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
                report_drafts=[_report_draft(status_label="Unconfirmed gray rollout feedback")],
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
                        report_id="missing_report_id",
                        decision=ReviewDecision.PASS,
                        reasoning_summary="Looks good.",
                    )
                ],
            ),
        ),
    )

    review = ReviewResultRepository(db_session).require(result.review_result_ids[0])
    assert review.report_id == report.id
    assert review.decision == ReviewDecision.PASS


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


def test_reviewer_materializer_aggregates_mixed_review_drafts(db_session) -> None:
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
                report_drafts=[
                    _report_draft(status_label="Unconfirmed gray rollout feedback")
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
                summary="Reviewer returned cluster-level decisions.",
                decision=ReviewDecision.REVISE,
                review_drafts=[
                    ReviewDraft(
                        report_id=report.id,
                        decision=ReviewDecision.PASS,
                        reasoning_summary="One cluster is acceptable.",
                    ),
                    ReviewDraft(
                        report_id=report.id,
                        decision=ReviewDecision.REVISE,
                        reasoning_summary="One cluster needs a caveat.",
                        issues=[
                            ReviewIssueDraft(
                                priority=1,
                                title="Missing caveat",
                                body="Add author-reported caveat to the claim.",
                            )
                        ],
                    ),
                ],
            ),
        ),
    )

    full_state = RunRepository(db_session).get_full_state(run.id)
    review = ReviewResultRepository(db_session).require(result.review_result_ids[0])
    updated_report = DailyReportRepository(db_session).require(report.id)
    assert result.review_result_ids == [review.id]
    assert len(full_state.review_results) == 1
    assert review.decision == ReviewDecision.REVISE
    assert review.issues[0].title == "Missing caveat"
    assert review.metadata["aggregated_review_drafts"] == 2
    assert updated_report.status == ReportStatus.NEEDS_REVISION


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
    evidence_ids: list[str] | None = None,
    cluster_ids: list[str] | None = None,
    potential_impact: str | None = (
        "If confirmed, agent frameworks may expose finer reasoning controls."
    ),
    key_data: list[str] | None = None,
    followup_points: list[str] | None = None,
    tomorrow_focus: list[str] | None = None,
    watchlist_updates: list[dict] | None = None,
) -> ReportDraft:
    return ReportDraft(
        report_id=report_id,
        overview_judgments=["Early API-surface signal is specific but unconfirmed."],
        tomorrow_focus=(
            tomorrow_focus
            if tomorrow_focus is not None
            else ["Check official changelog and SDK commits."]
        ),
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
                        potential_impact=potential_impact,
                        key_data=key_data or [],
                        evidence_ids=evidence_ids
                        or ["ev_openai_hn_reasoning", "ev_openai_wrapper_commit"],
                        cluster_ids=cluster_ids or ["cl_openai_reasoning_api"],
                        followup_points=(
                            followup_points
                            if followup_points is not None
                            else ["Check official docs and first-party SDK commits."]
                        ),
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
