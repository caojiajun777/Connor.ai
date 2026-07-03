"""Validation tests for Connor.ai domain contracts."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.domain import (
    AgentRole,
    CandidateCategory,
    CandidateItem,
    EvaluationDecision,
    EvaluationResult,
    EvaluationType,
    EvidenceStrength,
    ReportItem,
    SignalStatus,
    TraceEvent,
    TraceEventType,
    TraceStatus,
    WatchTier,
    WatchlistItem,
)
from tests.domain.fixtures import BASE_TIME, RUN_ID, early_signal_bundle


def test_candidate_requires_evidence_unless_manual_hypothesis() -> None:
    with pytest.raises(ValidationError):
        CandidateItem(
            id="cand_no_evidence",
            run_id=RUN_ID,
            category=CandidateCategory.EARLY_SIGNAL,
            signal_status=SignalStatus.GRAY_ROLLOUT_FEEDBACK,
            claim_summary="A signal without evidence should fail.",
            followup_questions=["Find evidence."],
            created_by_agent=AgentRole.SOCIAL_SCOUT,
        )

    hypothesis = CandidateItem(
        id="cand_manual_hypothesis",
        run_id=RUN_ID,
        category=CandidateCategory.EARLY_SIGNAL,
        signal_status=SignalStatus.MANUAL_HYPOTHESIS,
        claim_summary="Manual hypothesis used to seed exploration.",
        followup_questions=["Find first evidence."],
        created_by_agent=AgentRole.ORCHESTRATOR,
    )
    assert hypothesis.evidence_ids == []


def test_early_signal_requires_uncertain_status_and_followups() -> None:
    with pytest.raises(ValidationError):
        CandidateItem(
            id="cand_bad_early",
            run_id=RUN_ID,
            category=CandidateCategory.EARLY_SIGNAL,
            signal_status=SignalStatus.CONFIRMED_FACT,
            claim_summary="Confirmed status cannot be used for an early signal.",
            evidence_ids=["ev_1"],
            created_by_agent=AgentRole.SOCIAL_SCOUT,
        )


def test_confirmed_event_requires_strong_or_official_evidence() -> None:
    with pytest.raises(ValidationError):
        CandidateItem(
            id="cand_weak_confirmed",
            run_id=RUN_ID,
            category=CandidateCategory.CONFIRMED_EVENT,
            signal_status=SignalStatus.OFFICIAL_CONFIRMATION,
            claim_summary="This should fail because evidence is weak.",
            evidence_ids=["ev_1"],
            evidence_strength=EvidenceStrength.WEAK,
            created_by_agent=AgentRole.OFFICIAL_SCOUT,
        )


def test_select_early_signal_is_allowed_with_low_confidence_but_requires_followups() -> None:
    early = early_signal_bundle()
    evaluation = early["evaluation"]
    assert isinstance(evaluation, EvaluationResult)
    assert evaluation.decision == EvaluationDecision.SELECT_EARLY_SIGNAL

    with pytest.raises(ValidationError):
        EvaluationResult(
            id="eval_bad_early",
            run_id=RUN_ID,
            cluster_id="cl_1",
            evaluator_type=EvaluationType.FRONTIER,
            created_by_agent=AgentRole.FRONTIER_EVALUATOR,
            dimension_scores={"novelty": 8},
            total_score=7,
            decision=EvaluationDecision.SELECT_EARLY_SIGNAL,
            reasoning_summary="Missing follow-up requirements should fail.",
        )


def test_watchlist_ttl_rules_are_enforced_by_tier() -> None:
    with pytest.raises(ValidationError):
        WatchlistItem(
            id="watch_bad_short",
            run_id=RUN_ID,
            topic="Too long short watch",
            thesis="Short watches cannot run forever.",
            watch_tier=WatchTier.SHORT,
            ttl_days=14,
            watch_until=BASE_TIME + timedelta(days=14),
            reactivation_rules=["Reactivate on new evidence."],
            created_at=BASE_TIME,
        )


def test_watch_until_must_be_after_creation() -> None:
    with pytest.raises(ValidationError):
        WatchlistItem(
            id="watch_bad_window",
            run_id=RUN_ID,
            topic="Bad watch window",
            thesis="watch_until must be later than created_at.",
            watch_tier=WatchTier.SHORT,
            ttl_days=3,
            watch_until=BASE_TIME - timedelta(days=1),
            reactivation_rules=["Reactivate on new evidence."],
            created_at=BASE_TIME,
        )


def test_trace_rejects_hidden_reasoning_keys() -> None:
    with pytest.raises(ValidationError):
        TraceEvent(
            id="trace_bad_cot",
            run_id=RUN_ID,
            seq=1,
            phase="evaluating",
            event_type=TraceEventType.EVALUATION_CREATED,
            status=TraceStatus.SUCCEEDED,
            summary="This trace tries to store hidden reasoning.",
            metadata={"chain_of_thought": "not allowed"},
        )


def test_report_item_rules_guard_early_signal_and_finance_items() -> None:
    with pytest.raises(ValidationError):
        ReportItem(
            item_id="bad_early_item",
            title="Bad early item",
            category=CandidateCategory.EARLY_SIGNAL,
            status_label="Unconfirmed",
            core_information="Missing uncertainty label.",
            why_it_matters="It should fail.",
            evidence_ids=["ev_1"],
            cluster_ids=["cl_1"],
        )

    with pytest.raises(ValidationError):
        ReportItem(
            item_id="bad_finance_item",
            title="Bad finance item",
            category=CandidateCategory.TECH_FINANCE,
            status_label="Market signal",
            core_information="Missing ticker and impact.",
            why_it_matters="It should fail.",
            evidence_ids=["ev_1"],
            cluster_ids=["cl_1"],
        )

