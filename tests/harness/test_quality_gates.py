"""Quality gate tests."""

from app.domain import (
    EvaluationDecision,
    EvaluationResult,
    EvaluationType,
    ReviewDecision,
    ReviewResult,
    ReportStatus,
    RunBudgets,
    RunPhase,
    RunState,
    RunStatus,
)
from app.harness import CollectGateOutcome, HarnessConfig, QualityGateService, WritingGateOutcome
from app.repositories import DailyReportRepository, EvaluationRepository, RunRepository
from tests.domain.fixtures import BASE_TIME, RUN_ID, daily_report_fixture, run_state_fixture


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
