"""Phase 9 Clusterer closed-loop tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from agentscope.credential import CredentialBase
from agentscope.message import Msg, TextBlock, ToolCallBlock
from agentscope.model import ChatModelBase, ChatResponse
from pydantic import BaseModel

from app.agents import AgentRunner, create_default_agent_role_registry
from app.clusterer import ClusterTaskFactory
from app.domain import AgentRole, RunBudgets, RunPhase, TraceEventType
from app.harness import AgentTask, CollectLoopHarness, DailyRunHarness, HarnessConfig
from app.repositories import (
    CandidateRepository,
    EvaluationRepository,
    EventClusterRepository,
    EvidenceRepository,
)
from app.services import TraceService
from app.tools import create_default_tool_registry
from tests.domain.fixtures import BASE_TIME, RUN_ID, run_state_fixture


ResponseFactory = Callable[[list[Msg], list[dict] | None, int], ChatResponse]


class ScriptedPhase9Model(ChatModelBase):
    """AgentScope model that scripts Scout and Clusterer responses."""

    class Parameters(BaseModel):
        pass

    def __init__(self, role: AgentRole, responses: list[ChatResponse | ResponseFactory]):
        super().__init__(
            credential=CredentialBase(name="test"),
            model=f"scripted-phase9-{role.value}",
            parameters=self.Parameters(),
            stream=False,
            max_retries=0,
        )
        self.role = role
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


def test_scouts_then_clusterer_create_one_confirmed_cluster(db_session) -> None:
    tool_registry = create_default_tool_registry()
    role_registry = create_default_agent_role_registry(tool_registry)
    models = {
        AgentRole.SOCIAL_SCOUT: ScriptedPhase9Model(
            AgentRole.SOCIAL_SCOUT,
            [manual_seed_tool_call(AgentRole.SOCIAL_SCOUT), final_scout_response(AgentRole.SOCIAL_SCOUT)],
        ),
        AgentRole.OFFICIAL_SCOUT: ScriptedPhase9Model(
            AgentRole.OFFICIAL_SCOUT,
            [manual_seed_tool_call(AgentRole.OFFICIAL_SCOUT), final_scout_response(AgentRole.OFFICIAL_SCOUT)],
        ),
        AgentRole.CLUSTERER: ScriptedPhase9Model(
            AgentRole.CLUSTERER,
            [final_clusterer_response],
        ),
    }
    agent_runner = AgentRunner(
        db_session,
        role_registry=role_registry,
        tool_registry=tool_registry,
        model_factory=lambda config: models[config.role],
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

    next_run, decisions = CollectLoopHarness(daily_harness.context).run(
        run,
        tasks_by_phase={
            RunPhase.SCOUTING: [
                AgentTask(
                    agent_role=AgentRole.SOCIAL_SCOUT,
                    phase=RunPhase.SCOUTING,
                    task="Find one early reasoning-control API signal.",
                ),
                AgentTask(
                    agent_role=AgentRole.OFFICIAL_SCOUT,
                    phase=RunPhase.SCOUTING,
                    task="Find one official reasoning-control API confirmation.",
                ),
            ],
            RunPhase.CLUSTERING: [
                ClusterTaskFactory().create_task(objective=fixture.objective)
            ],
        },
    )

    evidence = EvidenceRepository(db_session).list_by_run(RUN_ID)
    candidates = CandidateRepository(db_session).list_by_run(RUN_ID)
    clusters = EventClusterRepository(db_session).list_by_run(RUN_ID)
    evaluations = EvaluationRepository(db_session).list_by_run(RUN_ID)

    assert next_run.phase == RunPhase.WRITING
    assert decisions[-1].outcome == "enter_writing"
    assert len(evidence) == 2
    assert len(candidates) == 2
    assert len(clusters) == 1
    assert len(evaluations) == 1
    assert clusters[0].category == "confirmed_event"
    assert clusters[0].candidate_ids == [candidate.id for candidate in candidates]
    assert clusters[0].metadata["materialized_by"] == "ClusterOutputMaterializer"
    assert clusters[0].metadata["confirmation_linked"] is True
    assert "bootstrap_single_agent" not in clusters[0].metadata
    assert evaluations[0].metadata["bootstrap_clusterer_evaluation"] is True
    assert next_run.selected_cluster_ids == [clusters[0].id]

    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)
    event_types = [event.event_type for event in timeline.events]
    assert event_types.count(TraceEventType.CANDIDATE_CREATED) == 2
    assert event_types.count(TraceEventType.CLUSTER_CREATED) == 1
    assert event_types.count(TraceEventType.EVALUATION_CREATED) == 1


def manual_seed_tool_call(role: AgentRole) -> ChatResponse:
    return ChatResponse(
        content=[
            ToolCallBlock(
                id=f"tool_call_phase9_{role.value}",
                name="manual_seed",
                input=json.dumps(
                    {
                        "query": f"seed phase9 {role.value}",
                        "params": {
                            "retrieved_at": BASE_TIME.isoformat(),
                            "items": [
                                {
                                    "title": f"Phase 9 source item for {role.value}",
                                    "url": f"https://example.com/phase9/{role.value}",
                                    "snippet": f"Deterministic source item for {role.value}.",
                                    "raw_hash": f"sha256:phase9-{role.value}",
                                }
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
            )
        ],
        is_last=True,
    )


def final_scout_response(role: AgentRole) -> ResponseFactory:
    def _response(messages: list[Msg], _tools: list[dict] | None, _call_index: int) -> ChatResponse:
        evidence_ids = evidence_ids_from_tool_results(messages)
        draft = {
            AgentRole.SOCIAL_SCOUT: {
                "category": "early_signal",
                "signal_status": "gray_rollout_feedback",
                "claim_summary": "Community reports suggest a reasoning-control API option is being tested.",
                "entities": ["OpenAI"],
                "topics": ["api", "reasoning"],
                "uncertainty": "medium",
                "evidence_strength": "moderate",
                "why_it_matters": "Reasoning controls may change developer cost and latency tradeoffs.",
                "potential_impact": "Agent frameworks may expose reasoning-budget controls.",
                "followup_questions": ["Check official API docs."],
            },
            AgentRole.OFFICIAL_SCOUT: {
                "category": "confirmed_event",
                "signal_status": "official_confirmation",
                "claim_summary": "Official docs confirm a reasoning-control API option.",
                "entities": ["OpenAI"],
                "topics": ["api", "reasoning"],
                "uncertainty": "high",
                "evidence_strength": "official",
                "why_it_matters": "Official confirmation changes the item from signal to event.",
                "potential_impact": "Developers can implement against the documented API surface.",
                "followup_questions": ["Check pricing, rate limits, and SDK support."],
            },
        }[role]
        payload = {
            "summary": f"{role.value} found one item.",
            "reasoning_summary": "The item is specific and trackable.",
            "evidence_ids": evidence_ids,
            "candidate_drafts": [{**draft, "evidence_ids": evidence_ids}],
        }
        return ChatResponse(
            content=[TextBlock(text=json.dumps(payload, ensure_ascii=False))],
            is_last=True,
        )

    return _response


def final_clusterer_response(
    messages: list[Msg],
    _tools: list[dict] | None,
    _call_index: int,
) -> ChatResponse:
    candidates = candidate_context_from_messages(messages)
    candidate_ids = [candidate["id"] for candidate in candidates]
    evidence_ids = [
        evidence_id
        for candidate in candidates
        for evidence_id in candidate["evidence_ids"]
    ]
    payload = {
        "summary": "Clusterer linked one early signal to one official confirmation.",
        "reasoning_summary": "Both candidates describe the same reasoning-control API surface.",
        "cluster_drafts": [
            {
                "category": "confirmed_event",
                "title": "OpenAI reasoning-control API confirmation",
                "canonical_claim": (
                    "Official docs confirm a reasoning-control API option that earlier "
                    "community reports pointed toward."
                ),
                "candidate_ids": candidate_ids,
                "evidence_ids": evidence_ids,
                "entities": ["OpenAI"],
                "topics": ["api", "reasoning"],
                "timeline": [
                    {
                        "summary": "Clusterer linked early community signal and official confirmation.",
                        "candidate_ids": candidate_ids,
                        "evidence_ids": evidence_ids,
                    }
                ],
                "conflict_summary": "No material conflict; the official docs clarify the early report.",
                "dedupe_key": "openai:reasoning-control-api",
            }
        ],
    }
    return ChatResponse(
        content=[TextBlock(text=json.dumps(payload, ensure_ascii=False))],
        is_last=True,
    )


def evidence_ids_from_tool_results(messages: list[Msg]) -> list[str]:
    evidence_ids: list[str] = []
    for message in messages:
        for block in message.get_content_blocks():
            if getattr(block, "type", None) != "tool_result":
                continue
            text = (
                block.output
                if isinstance(block.output, str)
                else "".join(item.text for item in block.output if isinstance(item, TextBlock))
            )
            evidence_ids.extend(json.loads(text)["evidence_ids"])
    return evidence_ids


def candidate_context_from_messages(messages: list[Msg]) -> list[dict[str, Any]]:
    for message in messages:
        text = message.get_text_content()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        context = payload.get("context", {})
        candidates = context.get("candidate_context")
        if isinstance(candidates, list):
            return candidates
    return []
