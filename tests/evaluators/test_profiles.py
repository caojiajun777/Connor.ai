"""Evaluator profile and task factory tests."""

from __future__ import annotations

import pytest

from app.agents.outputs import EvaluationDraft
from app.domain import AgentRole, CandidateCategory, EvaluationDecision, EvaluationType
from app.evaluators.profiles import (
    EvaluatorProfileError,
    create_default_evaluator_profile_registry,
)
from app.evaluators.tasks import EvaluatorTaskFactory
from tests.domain.fixtures import confirmed_event_bundle, early_signal_bundle, tech_finance_bundle


def test_default_registry_covers_three_evaluator_roles() -> None:
    registry = create_default_evaluator_profile_registry()

    assert registry.require(AgentRole.FRONTIER_EVALUATOR).evaluator_type == EvaluationType.FRONTIER
    assert registry.require(AgentRole.EVENT_EVALUATOR).evaluator_type == EvaluationType.EVENT
    assert registry.require(AgentRole.MARKET_EVALUATOR).evaluator_type == EvaluationType.MARKET


def test_evaluator_task_factory_embeds_profile_contract() -> None:
    task = EvaluatorTaskFactory().create_task(
        role=AgentRole.FRONTIER_EVALUATOR,
        objective="Evaluate frontier signals.",
    )

    assert task.agent_role == AgentRole.FRONTIER_EVALUATOR
    assert task.phase == "evaluating"
    assert task.context["evaluator_profile"]["evaluator_type"] == "frontier"
    assert "evaluation_drafts" in task.context["evaluation_output_contract"]


def test_event_profile_rejects_early_signal_cluster() -> None:
    registry = create_default_evaluator_profile_registry()
    profile = registry.require(AgentRole.EVENT_EVALUATOR)
    cluster = early_signal_bundle()["cluster"]
    draft = EvaluationDraft(
        cluster_id=cluster.id,
        evaluator_type=EvaluationType.EVENT,
        dimension_scores={
            "confirmation_strength": 9,
            "impact_scale": 7,
            "expectation_change": 6,
            "product_impact": 7,
        },
        total_score=7,
        decision=EvaluationDecision.SELECT_CONFIRMED,
        reasoning_summary="Official confirmation would be material.",
    )

    with pytest.raises(EvaluatorProfileError, match="cannot evaluate early_signal"):
        profile.validate_draft(draft, cluster)


def test_frontier_profile_accepts_trackable_unconfirmed_signal() -> None:
    registry = create_default_evaluator_profile_registry()
    profile = registry.require(AgentRole.FRONTIER_EVALUATOR)
    cluster = early_signal_bundle()["cluster"]
    draft = EvaluationDraft(
        cluster_id=cluster.id,
        evaluator_type=EvaluationType.FRONTIER,
        dimension_scores={
            "information_gap": 8,
            "specificity": 7,
            "source_proximity": 4,
            "potential_impact": 8,
            "trackability": 9,
        },
        total_score=7.2,
        decision=EvaluationDecision.SELECT_EARLY_SIGNAL,
        reasoning_summary="Specific, trackable, and valuable despite lacking official confirmation.",
        required_followups=["Monitor official changelog."],
        missing_evidence=["No official changelog confirmation yet."],
    )

    profile.validate_draft(draft, cluster)


def test_market_profile_requires_required_dimensions_and_ticker_path() -> None:
    registry = create_default_evaluator_profile_registry()
    profile = registry.require(AgentRole.MARKET_EVALUATOR)
    cluster = tech_finance_bundle()["cluster"]
    incomplete_draft = EvaluationDraft(
        cluster_id=cluster.id,
        evaluator_type=EvaluationType.MARKET,
        dimension_scores={
            "ai_relevance": 8,
            "market_impact": 7,
            "ticker_relevance": 8,
        },
        total_score=7.5,
        decision=EvaluationDecision.SELECT_CONFIRMED,
        reasoning_summary="Missing supply-chain dimension.",
    )

    with pytest.raises(EvaluatorProfileError, match="supply_chain_impact"):
        profile.validate_draft(incomplete_draft, cluster)


def test_cluster_context_includes_linked_candidates_and_evidence() -> None:
    early = early_signal_bundle()
    event = confirmed_event_bundle()

    context = EvaluatorTaskFactory.cluster_context(
        clusters=[early["cluster"], event["cluster"]],
        candidates=[early["candidate"], event["candidate"]],
        evidence=[*early["evidence"], *event["evidence"]],
    )

    assert context[0]["id"] == early["cluster"].id
    assert context[0]["category"] == CandidateCategory.EARLY_SIGNAL.value
    assert context[0]["candidate_summaries"] == [early["candidate"].claim_summary]
    assert context[0]["evidence_titles"] == [item.title for item in early["evidence"]]
