"""Writing task context tests."""

from app.domain import EvaluationDecision, EvaluationType
from app.repositories.runs import FullRunState
from app.writing.tasks import WritingTaskFactory
from tests.domain.fixtures import (
    confirmed_event_bundle,
    daily_report_fixture,
    early_signal_bundle,
    run_state_fixture,
    tech_finance_bundle,
)


def test_writer_context_includes_report_quality_contract() -> None:
    early = early_signal_bundle()
    official = confirmed_event_bundle()
    official_evaluation = official["evaluation"].model_copy(
        update={
            "decision": EvaluationDecision.FOLLOWUP_NOW,
            "required_followups": ["Collect benchmark details."],
            "missing_evidence": ["Benchmark table missing."],
        }
    )
    run = run_state_fixture().model_copy(
        update={
            "selected_cluster_ids": [
                early["cluster"].id,
                official["cluster"].id,
            ]
        }
    )
    full_state = FullRunState(
        run=run,
        evidence=[*early["evidence"], *official["evidence"]],
        candidates=[early["candidate"], official["candidate"]],
        clusters=[early["cluster"], official["cluster"]],
        evaluations=[early["evaluation"], official_evaluation],
        watchlist=[],
        archives=[],
        threads=[],
        reports=[],
        trace_events=[],
        tool_calls=[],
        model_calls=[],
        artifacts=[],
        review_results=[],
        review_issues=[],
    )

    context = WritingTaskFactory.writer_context(full_state)

    assert context["report_quality_contract"]["required_buckets"] == [
        "early_signals",
        "confirmed_events",
    ]
    clusters_by_id = {cluster["id"]: cluster for cluster in context["selected_clusters"]}
    assert clusters_by_id[early["cluster"].id]["write_policy"] == "write_now"
    assert clusters_by_id[official["cluster"].id]["write_policy"] == "write_with_caveat"
    assert clusters_by_id[official["cluster"].id]["report_bucket"] == "confirmed_events"
    assert clusters_by_id[official["cluster"].id]["missing_evidence"] == [
        "Benchmark table missing."
    ]
    assert context["report_quality_contract"]["selected_cluster_rule"]


def test_writer_context_maps_market_followup_to_finance_bucket() -> None:
    finance = tech_finance_bundle()
    finance_evaluation = finance["evaluation"].model_copy(
        update={
            "decision": EvaluationDecision.FOLLOWUP_NOW,
            "evaluator_type": EvaluationType.MARKET,
            "required_followups": ["Extract datacenter revenue."],
            "missing_evidence": ["Segment revenue not extracted."],
        }
    )
    run = run_state_fixture().model_copy(
        update={"selected_cluster_ids": [finance["cluster"].id]}
    )
    full_state = FullRunState(
        run=run,
        evidence=finance["evidence"],
        candidates=[finance["candidate"]],
        clusters=[finance["cluster"]],
        evaluations=[finance_evaluation],
        watchlist=[],
        archives=[],
        threads=[],
        reports=[],
        trace_events=[],
        tool_calls=[],
        model_calls=[],
        artifacts=[],
        review_results=[],
        review_issues=[],
    )

    context = WritingTaskFactory.writer_context(full_state)

    assert context["report_quality_contract"]["required_buckets"] == ["tech_finance"]
    cluster = context["selected_clusters"][0]
    assert cluster["report_bucket"] == "tech_finance"
    assert cluster["write_policy"] == "write_with_caveat"
    assert cluster["required_followups"] == ["Extract datacenter revenue."]


def test_reviewer_context_is_compact_and_marks_missing_selected_clusters() -> None:
    early = early_signal_bundle()
    finance = tech_finance_bundle()
    official = confirmed_event_bundle()
    report = daily_report_fixture()
    run = run_state_fixture().model_copy(
        update={
            "selected_cluster_ids": [
                early["cluster"].id,
                finance["cluster"].id,
                official["cluster"].id,
            ]
        }
    )
    full_state = FullRunState(
        run=run,
        evidence=[*early["evidence"], *finance["evidence"], *official["evidence"]],
        candidates=[early["candidate"], finance["candidate"], official["candidate"]],
        clusters=[early["cluster"], finance["cluster"], official["cluster"]],
        evaluations=[early["evaluation"], finance["evaluation"], official["evaluation"]],
        watchlist=[],
        archives=[],
        threads=[],
        reports=[report],
        trace_events=[],
        tool_calls=[],
        model_calls=[],
        artifacts=[],
        review_results=[],
        review_issues=[],
    )

    context = WritingTaskFactory.reviewer_context(full_state)

    assert context["report"]["id"] == report.id
    assert "full_markdown" not in context["report"]
    assert "full_markdown_excerpt" not in context["report"]
    assert context["report"]["full_markdown_available"] is True
    assert context["report"]["full_markdown_length"] == len(report.full_markdown)
    assert context["missing_selected_cluster_ids"] == [official["cluster"].id]
    assert official["cluster"].id in {cluster["id"] for cluster in context["clusters"]}
    assert all("raw_hash" not in evidence for evidence in context["evidence"])
    assert context["review_focus"][3] == (
        "Verify every selected cluster appears in at least one report item."
    )
