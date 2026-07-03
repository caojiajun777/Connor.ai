"""Phase 7 single-agent closed-loop tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from agentscope.credential import CredentialBase
from agentscope.message import Msg, TextBlock, ToolCallBlock
from agentscope.model import ChatModelBase, ChatResponse
from pydantic import BaseModel

from app.agents import AgentRunner, create_default_agent_role_registry
from app.domain import AgentRole, RunBudgets, RunPhase, TraceEventType
from app.harness import AgentTask, CollectLoopHarness, DailyRunHarness, HarnessConfig
from app.repositories import (
    CandidateRepository,
    EvaluationRepository,
    EventClusterRepository,
    EvidenceRepository,
    RunRepository,
)
from app.services import TraceService
from app.tools import create_default_tool_registry
from tests.domain.fixtures import BASE_TIME, RUN_ID, run_state_fixture


ResponseFactory = Callable[[list[Msg], list[dict] | None, int], ChatResponse]


class ScriptedScoutModel(ChatModelBase):
    """AgentScope model that first calls a tool, then returns a candidate draft."""

    class Parameters(BaseModel):
        pass

    def __init__(self, responses: list[ChatResponse | ResponseFactory]):
        super().__init__(
            credential=CredentialBase(name="test"),
            model="scripted-single-scout",
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


def manual_seed_tool_call() -> ChatResponse:
    return ChatResponse(
        content=[
            ToolCallBlock(
                id="tool_call_phase7_manual_seed",
                name="manual_seed",
                input=json.dumps(
                    {
                        "query": "seed phase7 OpenAI reasoning API signal",
                        "params": {
                            "retrieved_at": BASE_TIME.isoformat(),
                            "items": [
                                {
                                    "title": "OpenAI reasoning API option appears in community report",
                                    "url": "https://example.com/phase7-openai-reasoning",
                                    "snippet": (
                                        "A community report claims a reasoning-control "
                                        "API option appeared in an error response."
                                    ),
                                    "raw_hash": "sha256:phase7-openai-reasoning",
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


def final_scout_candidate_response(
    messages: list[Msg],
    _tools: list[dict] | None,
    _call_index: int,
) -> ChatResponse:
    evidence_ids = []
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

    return ChatResponse(
        content=[
            TextBlock(
                text=json.dumps(
                    {
                        "summary": "Found one OpenAI reasoning API early signal.",
                        "reasoning_summary": "The signal is specific and trackable.",
                        "evidence_ids": evidence_ids,
                        "candidate_drafts": [
                            {
                                "category": "early_signal",
                                "signal_status": "gray_rollout_feedback",
                                "claim_summary": (
                                    "Community evidence suggests OpenAI may be testing "
                                    "a reasoning-control API option."
                                ),
                                "entities": ["OpenAI"],
                                "topics": ["api", "reasoning", "developer_tools"],
                                "uncertainty": "low",
                                "evidence_strength": "moderate",
                                "why_it_matters": (
                                    "Reasoning controls could affect developer cost, "
                                    "latency, and agent orchestration."
                                ),
                                "potential_impact": (
                                    "Agent frameworks may need to expose reasoning-budget controls."
                                ),
                                "followup_questions": [
                                    "Check official OpenAI API docs and SDK commits."
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
            )
        ],
        is_last=True,
    )


def test_single_scout_agent_creates_evidence_candidate_cluster_and_evaluation(db_session) -> None:
    tool_registry = create_default_tool_registry()
    role_registry = create_default_agent_role_registry(tool_registry)
    model = ScriptedScoutModel([manual_seed_tool_call(), final_scout_candidate_response])
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
    run = daily_harness.create_run(
        run_id=RUN_ID,
        report_date=run_state_fixture().report_date,
        objective=run_state_fixture().objective,
        budgets=RunBudgets(max_collect_rounds=2),
    )

    next_run, decisions = CollectLoopHarness(daily_harness.context).run(
        run,
        tasks_by_phase={
            RunPhase.SCOUTING: [
                AgentTask(
                    agent_role=AgentRole.SOCIAL_SCOUT,
                    phase=RunPhase.SCOUTING,
                    task="Find one trackable OpenAI reasoning API early signal.",
                )
            ]
        },
    )

    evidence = EvidenceRepository(db_session).list_by_run(RUN_ID)
    candidates = CandidateRepository(db_session).list_by_run(RUN_ID)
    clusters = EventClusterRepository(db_session).list_by_run(RUN_ID)
    evaluations = EvaluationRepository(db_session).list_by_run(RUN_ID)
    persisted_run = RunRepository(db_session).require(RUN_ID)

    assert next_run.phase == RunPhase.WRITING
    assert decisions[-1].outcome == "enter_writing"
    assert len(evidence) == 1
    assert len(candidates) == 1
    assert candidates[0].evidence_ids == [evidence[0].id]
    assert candidates[0].created_by_agent == AgentRole.SOCIAL_SCOUT
    assert len(clusters) == 1
    assert clusters[0].candidate_ids == [candidates[0].id]
    assert clusters[0].metadata["bootstrap_single_agent"] is True
    assert len(evaluations) == 1
    assert evaluations[0].decision == "select_early_signal"
    assert evaluations[0].metadata["bootstrap_single_agent"] is True
    assert persisted_run.candidate_ids == [candidates[0].id]
    assert persisted_run.cluster_ids == [clusters[0].id]
    assert persisted_run.selected_cluster_ids == [clusters[0].id]

    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)
    event_types = [event.event_type for event in timeline.events]
    assert TraceEventType.TOOL_CALL_COMPLETED in event_types
    assert TraceEventType.EVIDENCE_CREATED in event_types
    assert TraceEventType.CANDIDATE_CREATED in event_types
    assert TraceEventType.CLUSTER_CREATED in event_types
    assert TraceEventType.EVALUATION_CREATED in event_types
    assert TraceEventType.GATE_DECISION in event_types
