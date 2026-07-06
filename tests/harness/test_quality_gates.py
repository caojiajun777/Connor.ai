"""Quality gate tests."""

from app.domain import (
    CandidateCategory,
    EvaluationDecision,
    EvaluationResult,
    EvaluationType,
    ReviewDecision,
    ReviewIssue,
    ReviewResult,
    ReportStatus,
    RunBudgets,
    RunPhase,
    RunState,
    RunStatus,
)
from app.harness import CollectGateOutcome, HarnessConfig, QualityGateService, WritingGateOutcome
from app.repositories import (
    CandidateRepository,
    DailyReportRepository,
    EvaluationRepository,
    EventClusterRepository,
    EvidenceRepository,
    RunRepository,
)
from tests.domain.fixtures import (
    BASE_TIME,
    RUN_ID,
    confirmed_event_bundle,
    daily_report_fixture,
    early_signal_bundle,
    run_state_fixture,
    tech_finance_bundle,
)


def test_collect_gate_requests_followup_when_no_selected_items(db_session) -> None:
    run = run_state_fixture().model_copy(
        update={
            "loop_counters": run_state_fixture().loop_counters.model_copy(
                update={"collect_rounds": 1}
            )
        }
    )
    RunRepository(db_session).add(run)
    EvaluationRepository(db_session).add(
        EvaluationResult(
            id="eval_followup",
            run_id=RUN_ID,
            cluster_id="cluster_missing",
            evaluator_type=EvaluationType.FRONTIER,
            created_by_agent="frontier_evaluator",
            dimension_scores={"specificity": 5, "trackability": 6},
            total_score=5.5,
            decision=EvaluationDecision.FOLLOWUP_NOW,
            reasoning_summary="Needs official changelog follow-up.",
            required_followups=["Check official API changelog."],
            created_at=BASE_TIME,
        )
    )
    db_session.flush()

    decision = QualityGateService().evaluate_collect(RunRepository(db_session).get_full_state(RUN_ID))

    assert decision.outcome == CollectGateOutcome.FOLLOWUP_NOW
    assert decision.followup_queries == ["Check official API changelog."]


def test_collect_gate_allows_followup_when_collect_round_budget_is_exhausted(db_session) -> None:
    run = run_state_fixture().model_copy(
        update={
            "budgets": RunBudgets(max_collect_rounds=1, max_followup_rounds=2),
            "loop_counters": run_state_fixture().loop_counters.model_copy(
                update={"collect_rounds": 1, "followup_rounds": 0}
            ),
        }
    )
    RunRepository(db_session).add(run)
    EvaluationRepository(db_session).add(
        EvaluationResult(
            id="eval_followup_at_collect_limit",
            run_id=RUN_ID,
            cluster_id="cluster_missing",
            evaluator_type=EvaluationType.FRONTIER,
            created_by_agent="frontier_evaluator",
            dimension_scores={"specificity": 5, "trackability": 6},
            total_score=5.5,
            decision=EvaluationDecision.FOLLOWUP_NOW,
            reasoning_summary="Needs targeted follow-up.",
            required_followups=["Check model card upload history."],
            created_at=BASE_TIME,
        )
    )
    db_session.flush()

    decision = QualityGateService().evaluate_collect(RunRepository(db_session).get_full_state(RUN_ID))

    assert decision.outcome == CollectGateOutcome.FOLLOWUP_NOW
    assert decision.followup_queries == ["Check model card upload history."]


def test_collect_gate_adds_required_report_bucket_coverage(db_session) -> None:
    run = run_state_fixture().model_copy(
        update={
            "loop_counters": run_state_fixture().loop_counters.model_copy(
                update={"collect_rounds": 1}
            )
        }
    )
    RunRepository(db_session).add(run)
    early = early_signal_bundle()
    official = _bundle_with_evaluation(
        confirmed_event_bundle(),
        decision=EvaluationDecision.FOLLOWUP_NOW,
        required_followups=["Collect official benchmark details."],
    )
    finance = _bundle_with_evaluation(
        tech_finance_bundle(),
        decision=EvaluationDecision.FOLLOWUP_NOW,
        required_followups=["Extract datacenter revenue and capex figures."],
    )
    for bundle in [early, official, finance]:
        _persist_bundle(db_session, bundle)
    db_session.flush()

    decision = QualityGateService().evaluate_collect(RunRepository(db_session).get_full_state(RUN_ID))

    assert decision.outcome == CollectGateOutcome.ENTER_WRITING
    assert decision.selected_cluster_ids == [
        "cl_openai_reasoning_api",
        "cl_anthropic_api_update",
        "cl_nvda_blackwell_hbm",
    ]
    assert decision.metadata["coverage_added_cluster_ids"] == [
        "cl_anthropic_api_update",
        "cl_nvda_blackwell_hbm",
    ]
    assert decision.metrics["selected_confirmed_events_count"] == 1
    assert decision.metrics["selected_tech_finance_count"] == 1


def test_collect_gate_pauses_when_budget_exhausted_without_selection(db_session) -> None:
    run = RunState(
        id=RUN_ID,
        report_date=run_state_fixture().report_date,
        objective=run_state_fixture().objective,
        phase=RunPhase.EVALUATION_GATE,
        status=RunStatus.RUNNING,
        budgets=RunBudgets(max_collect_rounds=1),
        loop_counters=run_state_fixture().loop_counters.model_copy(update={"collect_rounds": 1}),
        created_at=BASE_TIME,
    )
    RunRepository(db_session).add(run)
    db_session.flush()

    decision = QualityGateService(HarnessConfig(manual_review_on_failure=True)).evaluate_collect(
        RunRepository(db_session).get_full_state(RUN_ID)
    )

    assert decision.outcome == CollectGateOutcome.NEEDS_MANUAL_REVIEW
    assert "collect_budget_exhausted" in decision.risk_flags


def test_writing_gate_finalizes_only_after_pass_review(db_session) -> None:
    run = run_state_fixture().model_copy(update={"phase": RunPhase.REVIEWING})
    RunRepository(db_session).add(run)
    report = daily_report_fixture().model_copy(update={"status": ReportStatus.DRAFT})
    DailyReportRepository(db_session).add(report)
    from app.repositories import ReviewResultRepository

    ReviewResultRepository(db_session).add(
        ReviewResult(
            id="review_pass",
            run_id=RUN_ID,
            report_id=report.id,
            decision=ReviewDecision.PASS,
            reasoning_summary="Report passes.",
            created_at=BASE_TIME,
        )
    )
    db_session.flush()

    decision = QualityGateService().evaluate_writing(RunRepository(db_session).get_full_state(RUN_ID))

    assert decision.outcome == WritingGateOutcome.FINALIZE
    assert decision.report_id == report.id


def test_writing_gate_blocks_pass_when_selected_cluster_is_missing(db_session) -> None:
    run = run_state_fixture().model_copy(
        update={
            "phase": RunPhase.REVIEWING,
            "selected_cluster_ids": [
                "cl_openai_reasoning_api",
                "cl_anthropic_api_update",
            ],
        }
    )
    RunRepository(db_session).add(run)
    _persist_bundle(db_session, early_signal_bundle())
    _persist_bundle(db_session, confirmed_event_bundle())
    report = daily_report_fixture().model_copy(update={"status": ReportStatus.DRAFT})
    DailyReportRepository(db_session).add(report)
    from app.repositories import ReviewResultRepository

    ReviewResultRepository(db_session).add(
        ReviewResult(
            id="review_pass_missing_cluster",
            run_id=RUN_ID,
            report_id=report.id,
            decision=ReviewDecision.PASS,
            reasoning_summary="Report passes.",
            created_at=BASE_TIME,
        )
    )
    db_session.flush()

    decision = QualityGateService().evaluate_writing(RunRepository(db_session).get_full_state(RUN_ID))

    assert decision.outcome == WritingGateOutcome.NEEDS_MANUAL_REVIEW
    assert "missing_selected_cluster:cl_anthropic_api_update" in decision.risk_flags
    assert "missing_report_bucket:confirmed_events" in decision.risk_flags


def test_writing_gate_does_not_count_watchlist_item_as_selected_cluster_body_coverage(
    db_session,
) -> None:
    run = run_state_fixture().model_copy(
        update={
            "phase": RunPhase.REVIEWING,
            "selected_cluster_ids": ["cl_openai_reasoning_api"],
        }
    )
    RunRepository(db_session).add(run)
    _persist_bundle(db_session, early_signal_bundle())
    base_report = daily_report_fixture()
    watchlist_item = base_report.sections[0].items[0].model_copy(
        update={"category": CandidateCategory.WATCHLIST_UPDATE}
    )
    report = base_report.model_copy(
        update={
            "status": ReportStatus.DRAFT,
            "sections": [
                base_report.sections[0].model_copy(
                    update={
                        "section_id": "watchlist",
                        "title": "Watchlist",
                        "items": [watchlist_item],
                    }
                )
            ],
            "full_json": {
                **base_report.full_json,
                "sections": [
                    {
                        "section_id": "watchlist",
                        "items": [watchlist_item.model_dump(mode="json")],
                    }
                ],
            },
        }
    )
    DailyReportRepository(db_session).add(report)
    from app.repositories import ReviewResultRepository

    ReviewResultRepository(db_session).add(
        ReviewResult(
            id="review_pass_watchlist_only",
            run_id=RUN_ID,
            report_id=report.id,
            decision=ReviewDecision.PASS,
            reasoning_summary="Report passes.",
            created_at=BASE_TIME,
        )
    )
    db_session.flush()

    decision = QualityGateService().evaluate_writing(RunRepository(db_session).get_full_state(RUN_ID))

    assert decision.outcome == WritingGateOutcome.NEEDS_MANUAL_REVIEW
    assert "missing_selected_cluster:cl_openai_reasoning_api" in decision.risk_flags
    assert "missing_report_bucket:early_signals" in decision.risk_flags


def test_writing_gate_blocks_pass_when_tomorrow_focus_is_missing(db_session) -> None:
    run = run_state_fixture().model_copy(update={"phase": RunPhase.REVIEWING})
    RunRepository(db_session).add(run)
    report = daily_report_fixture().model_copy(
        update={
            "status": ReportStatus.DRAFT,
            "full_json": {
                **daily_report_fixture().full_json,
                "tomorrow_focus": [],
            },
        }
    )
    DailyReportRepository(db_session).add(report)
    from app.repositories import ReviewResultRepository

    ReviewResultRepository(db_session).add(
        ReviewResult(
            id="review_pass_missing_focus",
            run_id=RUN_ID,
            report_id=report.id,
            decision=ReviewDecision.PASS,
            reasoning_summary="Report passes.",
            created_at=BASE_TIME,
        )
    )
    db_session.flush()

    decision = QualityGateService().evaluate_writing(RunRepository(db_session).get_full_state(RUN_ID))

    assert decision.outcome == WritingGateOutcome.NEEDS_MANUAL_REVIEW
    assert "missing_tomorrow_focus" in decision.risk_flags


def test_writing_gate_finalizes_non_blocking_revisions_after_budget(db_session) -> None:
    base_run = run_state_fixture()
    run = base_run.model_copy(
        update={
            "phase": RunPhase.REVIEWING,
            "loop_counters": base_run.loop_counters.model_copy(
                update={"review_rounds": 2, "writing_rounds": 3}
            ),
        }
    )
    RunRepository(db_session).add(run)
    DailyReportRepository(db_session).add(daily_report_fixture())
    from app.repositories import ReviewResultRepository

    ReviewResultRepository(db_session).add(
        ReviewResult(
            id="review_revise_non_blocking",
            run_id=RUN_ID,
            report_id=daily_report_fixture().id,
            decision=ReviewDecision.REVISE,
            issues=[
                ReviewIssue(
                    id="issue_non_blocking",
                    run_id=RUN_ID,
                    report_id=daily_report_fixture().id,
                    priority=2,
                    title="Minor follow-up wording",
                    body="Make follow-up wording more specific.",
                    created_at=BASE_TIME,
                )
            ],
            required_changes=["Make follow-up wording more specific."],
            reasoning_summary="Report is structurally complete with minor revisions.",
            created_at=BASE_TIME,
        )
    )
    db_session.flush()

    decision = QualityGateService().evaluate_writing(RunRepository(db_session).get_full_state(RUN_ID))

    assert decision.outcome == WritingGateOutcome.FINALIZE
    assert "finalized_with_non_blocking_review_findings" in decision.risk_flags


def _persist_bundle(db_session, bundle: dict[str, object]) -> None:
    EvidenceRepository(db_session).add_many(bundle.get("evidence", []))
    CandidateRepository(db_session).add(bundle["candidate"])
    EventClusterRepository(db_session).add(bundle["cluster"])
    EvaluationRepository(db_session).add(bundle["evaluation"])


def _bundle_with_evaluation(
    bundle: dict[str, object],
    *,
    decision: EvaluationDecision,
    required_followups: list[str],
) -> dict[str, object]:
    evaluation = bundle["evaluation"].model_copy(
        update={
            "decision": decision,
            "required_followups": required_followups,
            "missing_evidence": required_followups,
        }
    )
    if evaluation.evaluator_type == EvaluationType.MARKET:
        evaluation = evaluation.model_copy(
            update={
                "dimension_scores": {
                    "ai_relevance": 9,
                    "market_impact": 8,
                    "supply_chain_impact": 8,
                    "ticker_relevance": 9,
                },
                "total_score": 8.5,
            }
        )
    if bundle["cluster"].category == CandidateCategory.CONFIRMED_EVENT:
        evaluation = evaluation.model_copy(
            update={
                "dimension_scores": {
                    "confirmation": 10,
                    "impact_scale": 7,
                    "expectation_change": 6,
                    "product_impact": 7,
                },
                "total_score": 7.5,
            }
        )
    return {**bundle, "evaluation": evaluation}
