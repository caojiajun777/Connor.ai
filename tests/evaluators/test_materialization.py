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
    TraceStatus,
    WritePolicy,
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


def test_evaluator_downgrades_weak_single_source_community_signal(db_session) -> None:
    context = HarnessContext(db_session)
    run = run_state_fixture()
    context.runs.add(run)
    weak = early_signal_bundle()
    weak_evidence = weak["evidence"][0].model_copy(
        update={"metadata": {"score": 1, "comment_count": 0}}
    )
    weak_candidate = weak["candidate"].model_copy(
        update={"evidence_ids": [weak_evidence.id]}
    )
    weak_cluster = weak["cluster"].model_copy(
        update={"evidence_ids": [weak_evidence.id]}
    )
    _persist_bundle_without_evaluation(
        db_session,
        {
            **weak,
            "evidence": [weak_evidence],
            "candidate": weak_candidate,
            "cluster": weak_cluster,
        },
    )

    materialized = EvaluatorOutputMaterializer(context).materialize(
        run=run,
        phase=RunPhase.EVALUATING,
        agent_role=AgentRole.FRONTIER_EVALUATOR,
        result=_result(
            role=AgentRole.FRONTIER_EVALUATOR,
            draft=EvaluationDraft(
                cluster_id=weak_cluster.id,
                evaluator_type=EvaluationType.FRONTIER,
                dimension_scores={
                    "information_gap": 8,
                    "specificity": 6,
                    "source_proximity": 3,
                    "potential_impact": 7,
                    "trackability": 8,
                },
                total_score=6.4,
                decision=EvaluationDecision.SELECT_EARLY_SIGNAL,
                reasoning_summary="Interesting but currently one weak community post.",
                required_followups=["Find another independent source."],
                missing_evidence=["No corroborating source yet."],
            ),
        ),
    )

    evaluation = EvaluationRepository(db_session).require(materialized.evaluation_ids[0])
    cluster = EventClusterRepository(db_session).require(weak_cluster.id)

    assert materialized.selected_cluster_ids == []
    assert evaluation.decision == EvaluationDecision.SHORT_WATCH
    assert evaluation.write_policy == WritePolicy.CONTEXT_ONLY
    assert evaluation.metadata["normalized_decision_reason"] == "weak_single_source_community_signal"
    assert cluster.selected is False


def test_evaluator_repairs_recluster_without_risk_flags(db_session) -> None:
    context = HarnessContext(db_session)
    run = run_state_fixture()
    context.runs.add(run)
    early = _persist_bundle_without_evaluation(db_session, early_signal_bundle())

    materialized = EvaluatorOutputMaterializer(context).materialize(
        run=run,
        phase=RunPhase.EVALUATING,
        agent_role=AgentRole.FRONTIER_EVALUATOR,
        result=_result(
            role=AgentRole.FRONTIER_EVALUATOR,
            draft=EvaluationDraft(
                cluster_id=early["cluster"].id,
                evaluator_type=EvaluationType.FRONTIER,
                dimension_scores={
                    "information_gap": 6,
                    "specificity": 5,
                    "source_proximity": 4,
                    "potential_impact": 5,
                    "trackability": 7,
                },
                total_score=5.4,
                decision=EvaluationDecision.RECLUSTER,
                reasoning_summary="The cluster may mix unrelated signals.",
            ),
        ),
    )

    evaluation = EvaluationRepository(db_session).require(materialized.evaluation_ids[0])

    assert evaluation.decision == EvaluationDecision.RECLUSTER
    assert evaluation.risk_flags == ["recluster_requested_without_risk_flags"]
    assert evaluation.metadata["repaired_missing_recluster_risk_flags"] is True


def test_invalid_evaluator_draft_raises_harness_error(db_session) -> None:
    context = HarnessContext(db_session)
    run = run_state_fixture()
    context.runs.add(run)
    event = _persist_bundle_without_evaluation(db_session, confirmed_event_bundle())

    materializer = EvaluatorOutputMaterializer(context)

    with pytest.raises(HarnessError, match="missing score dimensions: product_impact"):
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
                    },
                    total_score=7.5,
                    decision=EvaluationDecision.SELECT_CONFIRMED,
                    reasoning_summary="Official source exists but one required dimension is missing.",
                ),
            ),
        )


def test_evaluator_skips_cluster_category_owned_by_another_profile(db_session) -> None:
    context = HarnessContext(db_session)
    run = run_state_fixture()
    context.runs.add(run)
    event = _persist_bundle_without_evaluation(db_session, confirmed_event_bundle())

    materializer = EvaluatorOutputMaterializer(context)
    materialized = materializer.materialize(
        run=run,
        phase=RunPhase.EVALUATING,
        agent_role=AgentRole.FRONTIER_EVALUATOR,
        result=_result(
            role=AgentRole.FRONTIER_EVALUATOR,
            draft=EvaluationDraft(
                cluster_id=event["cluster"].id,
                evaluator_type=EvaluationType.FRONTIER,
                dimension_scores={
                    "information_gap": 8,
                    "specificity": 7,
                    "source_proximity": 4,
                    "potential_impact": 8,
                    "trackability": 9,
                },
                total_score=7.2,
                decision=EvaluationDecision.FOLLOWUP_NOW,
                reasoning_summary="This draft targets a cluster owned by Event Evaluator.",
                required_followups=["Let event evaluator judge this cluster."],
            ),
        ),
    )

    evaluations = EvaluationRepository(db_session).list_by_run(RUN_ID)
    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)

    assert materialized.evaluation_ids == []
    assert evaluations == []
    assert timeline.events[-1].event_type == TraceEventType.AGENT_DECISION
    assert timeline.events[-1].status == TraceStatus.SKIPPED
    assert timeline.events[-1].metadata["skip_reason"] == "ineligible_cluster_category"


def test_evaluator_skips_missing_cluster_id(db_session) -> None:
    context = HarnessContext(db_session)
    run = run_state_fixture()
    context.runs.add(run)

    materializer = EvaluatorOutputMaterializer(context)
    materialized = materializer.materialize(
        run=run,
        phase=RunPhase.EVALUATING,
        agent_role=AgentRole.FRONTIER_EVALUATOR,
        result=_result(
            role=AgentRole.FRONTIER_EVALUATOR,
            draft=EvaluationDraft(
                cluster_id="missing_cluster",
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
                reasoning_summary="This draft targets a missing cluster.",
            ),
        ),
    )

    evaluations = EvaluationRepository(db_session).list_by_run(RUN_ID)
    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)

    assert materialized.evaluation_ids == []
    assert evaluations == []
    assert timeline.events[-1].status == TraceStatus.SKIPPED
    assert timeline.events[-1].metadata["skip_reason"] == "missing_or_wrong_run_cluster"


def test_evaluator_normalizes_summed_or_percent_scores(db_session) -> None:
    context = HarnessContext(db_session)
    run = run_state_fixture()
    context.runs.add(run)
    early = _persist_bundle_without_evaluation(db_session, early_signal_bundle())

    materializer = EvaluatorOutputMaterializer(context)
    materializer.materialize(
        run=run,
        phase=RunPhase.EVALUATING,
        agent_role=AgentRole.FRONTIER_EVALUATOR,
        result=_result(
            role=AgentRole.FRONTIER_EVALUATOR,
            draft=EvaluationDraft(
                cluster_id=early["cluster"].id,
                evaluator_type=EvaluationType.FRONTIER,
                dimension_scores={
                    "information_gap": 80,
                    "specificity": 70,
                    "source_proximity": 40,
                    "potential_impact": 80,
                    "trackability": 90,
                },
                total_score=360,
                decision=EvaluationDecision.SELECT_EARLY_SIGNAL,
                reasoning_summary="The model used percent dimensions and summed total.",
                required_followups=["Monitor official API changelog."],
                missing_evidence=["No official confirmation."],
            ),
        ),
    )

    evaluations = EvaluationRepository(db_session).list_by_run(RUN_ID)
    assert len(evaluations) == 1
    assert evaluations[0].dimension_scores["information_gap"] == 8
    assert evaluations[0].total_score == pytest.approx(7.2)
    assert evaluations[0].metadata["normalized_total_score_from"] == 360
    assert evaluations[0].metadata["normalized_dimension_scores_from"]["trackability"] == 90


def test_evaluator_downgrades_low_score_confirmed_selection(db_session) -> None:
    context = HarnessContext(db_session)
    run = run_state_fixture()
    context.runs.add(run)
    event = _persist_bundle_without_evaluation(db_session, confirmed_event_bundle())

    materializer = EvaluatorOutputMaterializer(context)
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
                    "confirmation_strength": 5,
                    "impact_scale": 4,
                    "expectation_change": 5,
                    "product_impact": 5,
                },
                total_score=4.75,
                decision=EvaluationDecision.SELECT_CONFIRMED,
                reasoning_summary="The model selected confirmed despite a low score.",
            ),
        ),
    )

    evaluations = EvaluationRepository(db_session).list_by_run(RUN_ID)
    assert len(evaluations) == 1
    assert evaluations[0].decision == EvaluationDecision.FOLLOWUP_NOW
    assert evaluations[0].required_followups
    assert evaluations[0].metadata["normalized_decision_from"] == "select_confirmed"


def test_evaluator_downgrades_confirmed_selection_with_missing_evidence(db_session) -> None:
    context = HarnessContext(db_session)
    run = run_state_fixture()
    context.runs.add(run)
    market = _persist_bundle_without_evaluation(db_session, tech_finance_bundle())

    materializer = EvaluatorOutputMaterializer(context)
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
                reasoning_summary="The model selected confirmed while listing missing evidence.",
                missing_evidence=["Need the latest segment-level disclosure."],
            ),
        ),
    )

    evaluations = EvaluationRepository(db_session).list_by_run(RUN_ID)
    assert len(evaluations) == 1
    assert evaluations[0].decision == EvaluationDecision.FOLLOWUP_NOW
    assert evaluations[0].required_followups == ["Need the latest segment-level disclosure."]
    assert "missing_evidence" in evaluations[0].metadata["normalized_decision_reason"]


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
