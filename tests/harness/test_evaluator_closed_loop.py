"""Phase 10 Evaluator Group closed-loop tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from agentscope.credential import CredentialBase
from agentscope.message import Msg, TextBlock
from agentscope.model import ChatModelBase, ChatResponse
from pydantic import BaseModel

from app.agents import AgentRunner, create_default_agent_role_registry
from app.domain import AgentRole, RunBudgets, RunPhase, TraceEventType
from app.evaluators import EvaluatorTaskFactory
from app.harness import CollectLoopHarness, DailyRunHarness, HarnessConfig
from app.repositories import (
    CandidateRepository,
    EvaluationRepository,
    EventClusterRepository,
    EvidenceRepository,
)
from app.services import TraceService
from app.tools import create_default_tool_registry
from tests.domain.fixtures import RUN_ID, early_signal_bundle, run_state_fixture


ResponseFactory = Callable[[list[Msg], list[dict] | None, int], ChatResponse]


class ScriptedPhase10Model(ChatModelBase):
    """AgentScope model that scripts one Frontier Evaluator response."""

    class Parameters(BaseModel):
        pass

    def __init__(self, responses: list[ChatResponse | ResponseFactory]):
        super().__init__(
            credential=CredentialBase(name="test"),
            model="scripted-phase10-frontier-evaluator",
            parameters=self.Parameters(),
            stream=False,
            max_retries=0,
        )
        self.responses = responses

    async def _call_api(
        self,
        model_name: str,
        messages: list[Msg],
        tools: list[dict] | None = None,
        tool_choice: Any | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        response = self.responses.pop(0)
        if callable(response):
            return response(messages, tools, len(self.responses))
        return response


def test_frontier_evaluator_replaces_clusterer_bootstrap_path(db_session) -> None:
    tool_registry = create_default_tool_registry()
    role_registry = create_default_agent_role_registry(tool_registry)
    model = ScriptedPhase10Model([final_frontier_evaluator_response])
    agent_runner = AgentRunner(
        db_session,
        role_registry=role_registry,
        tool_registry=tool_registry,
        model_factory=lambda _config: model,
    )
    daily_harness = DailyRunHarness(
        db_session,
        agent_runner=agent_runner,
        config=HarnessConfig(min_selected_items=1),
    )
    fixture = run_state_fixture()
    run = daily_harness.create_run(
        run_id=RUN_ID,
        report_date=fixture.report_date,
        objective=fixture.objective,
        budgets=RunBudgets(max_collect_rounds=2),
    )
    _persist_bundle_without_evaluation(db_session, early_signal_bundle())

    next_run, decisions = CollectLoopHarness(daily_harness.context).run(
        run,
        tasks_by_phase={
            RunPhase.EVALUATING: [
                EvaluatorTaskFactory().create_task(
                    role=AgentRole.FRONTIER_EVALUATOR,
                    objective=fixture.objective,
                )
            ],
        },
    )

    evaluations = EvaluationRepository(db_session).list_by_run(RUN_ID)
    cluster = EventClusterRepository(db_session).require("cl_openai_reasoning_api")
    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)

    assert next_run.phase == RunPhase.WRITING
    assert decisions[-1].outcome == "enter_writing"
    assert next_run.selected_cluster_ids == [cluster.id]
    assert cluster.selected is True
    assert len(evaluations) == 1
    assert evaluations[0].created_by_agent == AgentRole.FRONTIER_EVALUATOR
    assert evaluations[0].decision == "select_early_signal"
    assert "bootstrap_clusterer_evaluation" not in evaluations[0].metadata
    assert evaluations[0].metadata["materialized_by"] == "EvaluatorOutputMaterializer"
    assert evaluations[0].required_followups == ["Monitor official API changelog."]
    assert (
        [event.event_type for event in timeline.events].count(TraceEventType.EVALUATION_CREATED)
        == 1
    )


def final_frontier_evaluator_response(
    messages: list[Msg],
    _tools: list[dict] | None,
    _call_index: int,
) -> ChatResponse:
    clusters = cluster_context_from_messages(messages)
    cluster_id = clusters[0]["id"]
    payload = {
        "summary": "Frontier evaluator selected one early signal.",
        "reasoning_summary": "The signal is specific and trackable but unconfirmed.",
        "evaluation_drafts": [
            {
                "cluster_id": cluster_id,
                "evaluator_type": "frontier",
                "dimension_scores": {
                    "information_gap": 8,
                    "specificity": 7,
                    "source_proximity": 4,
                    "potential_impact": 8,
                    "trackability": 9,
                },
                "total_score": 7.2,
                "decision": "select_early_signal",
                "reasoning_summary": "Specific, trackable, and valuable despite lacking confirmation.",
                "required_followups": ["Monitor official API changelog."],
                "missing_evidence": ["No official changelog confirmation yet."],
            }
        ],
    }
    return ChatResponse(
        content=[TextBlock(text=json.dumps(payload, ensure_ascii=False))],
        is_last=True,
    )


def cluster_context_from_messages(messages: list[Msg]) -> list[dict[str, Any]]:
    for message in messages:
        text = message.get_text_content()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        context = payload.get("context", {})
        clusters = context.get("cluster_context")
        if isinstance(clusters, list):
            return clusters
    return []


def _persist_bundle_without_evaluation(db_session, bundle: dict[str, object]) -> None:
    EvidenceRepository(db_session).add_many(bundle.get("evidence", []))
    CandidateRepository(db_session).add(bundle["candidate"])
    EventClusterRepository(db_session).add(bundle["cluster"])
