"""Evaluator output materialization tests."""

from __future__ import annotations

import pytest

from app.agents import AgentRunResult
from app.agents.outputs import EvaluationDraft, EvaluatorOutput
from app.domain import (
    AgentRole,
    EvaluationDecision,
    EvaluationType,
    RunPhase,
    TraceEventType,
)
from app.evaluators.materialization import EvaluatorOutputMaterializer
from app.exceptions import HarnessError
from app.harness import HarnessContext
from app.repositories import (
    CandidateRepository,
    EvaluationRepository,
    EventClusterRepository,
    EvidenceRepository,
)
from app.services import TraceService
from tests.domain.fixtures import (
    RUN_ID,
    confirmed_event_bundle,
    early_signal_bundle,
    run_state_fixture,
    tech_finance_bundle,
)


def test_evaluator_outputs_materialize_to_evaluations_and_trace(db_session) -> None:
    context = HarnessContext(db_session)
    run = run_state_fixture()
    context.runs.add(run)
    early = _persist_bundle_without_evaluation(db_session, early_signal_bundle())
    event = _persist_bundle_without_evaluation(db_session, confirmed_event_bundle())
    market = _persist_bundle_without_evaluation(db_session, tech_finance_bundle())

    materializer = EvaluatorOutputMaterializer(context)
    frontier = materializer.materialize(
        run=run,
        phase=RunPhase.EVALUATING,
        agent_role=AgentRole.FRONTIER_EVALUATOR,
        result=_result(
            role=AgentRole.FRONTIER_EVALUATOR,
            draft=EvaluationDraft(
                cluster_id=early["cluster"].id,
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
                reasoning_summary="Specific and trackable, but still unconfirmed.",
                required_followups=["Monitor official API changelog."],
                missing_evidence=["No official API changelog confirmation yet."],
            ),
        ),
    )
    materializer.materialize(
        run=run,
        phase=RunPhase.EVALUATING,
        agent_role=AgentRole.EVENT_EVALUATOR,
        result=_result(
            role=AgentRole.EVENT_EVALUATOR,
            draft=EvaluationDraft(
                cluster_id=event["cluster"].id,
                evaluator_type=EvaluationType.EVENT,
                dimension_scores={
                    "confirmation_strength": 10,
                    "impact_scale": 7,
                    "expectation_change": 6,
                    "product_impact": 7,
                },
                total_score=7.5,
                decision=EvaluationDecision.SELECT_CONFIRMED,
                reasoning_summary="Official changelog confirms a material API update.",
            ),
        ),
    )
    materializer.materialize(
        run=run,
        phase=RunPhase.EVALUATING,
        agent_role=AgentRole.MARKET_EVALUATOR,
        result=_result(
            role=AgentRole.MARKET_EVALUATOR,
            draft=EvaluationDraft(
                cluster_id=market["cluster"].id,
                evaluator_type=EvaluationType.MARKET,
                dimension_scores={
                    "ai_relevance": 9,
                    "market_impact": 8,
                    "supply_chain_impact": 8,
                    "ticker_relevance": 9,
                },
                total_score=8.5,
                decision=EvaluationDecision.SELECT_CONFIRMED,
                reasoning_summary="Clear AI demand and supply-chain implication chain.",
            ),
        ),
    )

    evaluations = EvaluationRepository(db_session).list_by_run(RUN_ID)
    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)
    selected_cluster = EventClusterRepository(db_session).require(early["cluster"].id)
    latest_run = context.runs.require(RUN_ID)

    assert len(frontier.evaluation_ids) == 1
    assert len(evaluations) == 3
    assert {evaluation.created_by_agent for evaluation in evaluations} == {
        AgentRole.FRONTIER_EVALUATOR,
        AgentRole.EVENT_EVALUATOR,
        AgentRole.MARKET_EVALUATOR,
    }
    assert all(
        evaluation.metadata["materialized_by"] == "EvaluatorOutputMaterializer"
        for evaluation in evaluations
    )
    assert selected_cluster.selected is True
    assert len(latest_run.metadata["evaluator_materialization"]) == 3
    assert (
        [event.event_type for event in timeline.events].count(TraceEventType.EVALUATION_CREATED)
        == 3
    )


def test_invalid_evaluator_draft_raises_harness_error(db_session) -> None:
    context = HarnessContext(db_session)
    run = run_state_fixture()
    context.runs.add(run)
    event = _persist_bundle_without_evaluation(db_session, confirmed_event_bundle())

    materializer = EvaluatorOutputMaterializer(context)

    with pytest.raises(HarnessError, match="select_confirmed cannot include missing_evidence"):
        materializer.materialize(
            run=run,
            phase=RunPhase.EVALUATING,
            agent_role=AgentRole.EVENT_EVALUATOR,
            result=_result(
                role=AgentRole.EVENT_EVALUATOR,
                draft=EvaluationDraft(
                    cluster_id=event["cluster"].id,
                    evaluator_type=EvaluationType.EVENT,
                    dimension_scores={
                        "confirmation_strength": 10,
                        "impact_scale": 7,
                        "expectation_change": 6,
                        "product_impact": 7,
                    },
                    total_score=7.5,
                    decision=EvaluationDecision.SELECT_CONFIRMED,
                    reasoning_summary="Official source exists but this draft contradicts itself.",
                    missing_evidence=["Still missing official source."],
                ),
            ),
        )


def _persist_bundle_without_evaluation(db_session, bundle: dict[str, object]) -> dict[str, object]:
    EvidenceRepository(db_session).add_many(bundle.get("evidence", []))
    CandidateRepository(db_session).add(bundle["candidate"])
    EventClusterRepository(db_session).add(bundle["cluster"])
    return bundle


def _result(*, role: AgentRole, draft: EvaluationDraft) -> AgentRunResult:
    return AgentRunResult(
        run_id=RUN_ID,
        phase=RunPhase.EVALUATING,
        agent_role=role,
        structured_output=EvaluatorOutput(
            summary=f"{role.value} evaluated one cluster.",
            evaluation_drafts=[draft],
        ),
    )
