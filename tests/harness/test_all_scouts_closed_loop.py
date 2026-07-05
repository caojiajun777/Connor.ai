"""Phase 8 all-Scout closed-loop tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from agentscope.credential import CredentialBase
from agentscope.message import Msg, TextBlock, ToolCallBlock
from agentscope.model import ChatModelBase, ChatResponse
from pydantic import BaseModel

from app.agents import AgentRunner, create_default_agent_role_registry
from app.domain import AgentRole, RunBudgets, RunPhase, TraceEventType
from app.harness import CollectLoopHarness, DailyRunHarness, HarnessConfig, HarnessError
from app.repositories import (
    CandidateRepository,
    EvaluationRepository,
    EventClusterRepository,
    EvidenceRepository,
    RunRepository,
)
from app.scouts import ScoutTaskFactory
from app.services import TraceService
from app.tools import create_default_tool_registry
from tests.domain.fixtures import BASE_TIME, RUN_ID, run_state_fixture


ResponseFactory = Callable[[list[Msg], list[dict] | None, int], ChatResponse]


class ScriptedScoutModel(ChatModelBase):
    """AgentScope model that first calls a tool, then returns a Scout candidate draft."""

    class Parameters(BaseModel):
        pass

    def __init__(self, role: AgentRole, responses: list[ChatResponse | ResponseFactory]):
        super().__init__(
            credential=CredentialBase(name="test"),
            model=f"scripted-{role.value}",
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


def manual_seed_tool_call(role: AgentRole) -> ChatResponse:
    return ChatResponse(
        content=[
            ToolCallBlock(
                id=f"tool_call_phase8_{role.value}",
                name="manual_seed",
                input=json.dumps(
                    {
                        "query": f"seed phase8 {role.value}",
                        "params": {
                            "retrieved_at": BASE_TIME.isoformat(),
                            "items": [
                                {
                                    "title": f"Phase 8 source item for {role.value}",
                                    "url": f"https://example.com/phase8/{role.value}",
                                    "snippet": f"Deterministic source item for {role.value}.",
                                    "raw_hash": f"sha256:phase8-{role.value}",
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
        evidence_ids = evidence_ids_from_messages(messages)
        payload = scout_payload(role, evidence_ids)
        return ChatResponse(
            content=[TextBlock(text=json.dumps(payload, ensure_ascii=False))],
            is_last=True,
        )

    return _response


def evidence_ids_from_messages(messages: list[Msg]) -> list[str]:
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


def scout_payload(role: AgentRole, evidence_ids: list[str]) -> dict[str, Any]:
    base = {
        "summary": f"{role.value} found one trackable item.",
        "reasoning_summary": "The item is specific, bounded, and has a follow-up path.",
        "evidence_ids": evidence_ids,
    }
    drafts = {
        AgentRole.SOCIAL_SCOUT: {
            "category": "early_signal",
            "signal_status": "gray_rollout_feedback",
            "claim_summary": "Community reports suggest a reasoning control may be in gray rollout.",
            "entities": ["OpenAI"],
            "topics": ["api", "reasoning"],
            "uncertainty": "medium",
            "evidence_strength": "moderate",
            "why_it_matters": "A reasoning control would affect agent runtime behavior.",
            "potential_impact": "Developer tools may need to expose reasoning-budget controls.",
            "followup_questions": ["Check official API docs and SDK release notes."],
        },
        AgentRole.CODE_MODEL_SCOUT: {
            "category": "code_model",
            "signal_status": "code_anomaly",
            "claim_summary": "A package-style anomaly suggests a new agent SDK surface may be preparing.",
            "entities": ["OpenAI"],
            "topics": ["sdk", "agents"],
            "uncertainty": "medium",
            "evidence_strength": "moderate",
            "why_it_matters": "SDK anomalies can precede productized agent features.",
            "potential_impact": "Agent frameworks may need compatibility updates.",
            "followup_questions": ["Track package metadata and related GitHub commits."],
        },
        AgentRole.RESEARCH_SCOUT: {
            "category": "research",
            "signal_status": "researcher_hint",
            "claim_summary": "A research signal points to renewed interest in long-horizon agent evaluation.",
            "entities": ["Academic labs"],
            "topics": ["agents", "benchmarks"],
            "uncertainty": "medium",
            "evidence_strength": "moderate",
            "why_it_matters": "Better agent benchmarks can shift model release narratives.",
            "potential_impact": "Frontier labs may adopt harder public evaluation sets.",
            "followup_questions": ["Watch for benchmark code and leaderboard updates."],
        },
        AgentRole.OFFICIAL_SCOUT: {
            "category": "official_update",
            "signal_status": "official_confirmation",
            "claim_summary": "An official changelog confirms a new API capability is available.",
            "entities": ["OpenAI"],
            "topics": ["api", "release_notes"],
            "uncertainty": "high",
            "evidence_strength": "official",
            "why_it_matters": "Official changelogs move a signal from rumor to confirmed event.",
            "potential_impact": "Developers can adopt the new capability immediately.",
            "followup_questions": ["Check pricing, limits, and SDK support."],
        },
        AgentRole.FINANCE_SCOUT: {
            "category": "tech_finance",
            "signal_status": "confirmed_fact",
            "claim_summary": "AI infrastructure spending remains a key driver for data-center suppliers.",
            "entities": ["NVIDIA"],
            "tickers": ["NVDA"],
            "topics": ["ai_capex", "datacenter"],
            "uncertainty": "high",
            "evidence_strength": "strong",
            "why_it_matters": "AI capex guidance can affect semiconductor and networking expectations.",
            "potential_impact": "Higher capex supports GPU, networking, and AI server demand.",
            "followup_questions": ["Track next IR update and supplier commentary."],
        },
    }
    return {**base, "candidate_drafts": [{**drafts[role], "evidence_ids": evidence_ids}]}


def invalid_finance_response(
    _messages: list[Msg],
    _tools: list[dict] | None,
    _call_index: int,
) -> ChatResponse:
    return ChatResponse(
        content=[
            TextBlock(
                text=json.dumps(
                    {
                        "summary": "Invalid finance Scout output.",
                        "reasoning_summary": "This deliberately violates the Finance Scout category.",
                        "candidate_drafts": [
                            {
                                "category": "early_signal",
                                "signal_status": "manual_hypothesis",
                                "claim_summary": "A model rumor is not a finance item.",
                                "uncertainty": "medium",
                                "evidence_strength": "moderate",
                                "followup_questions": ["Look for evidence."],
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
            )
        ],
        is_last=True,
    )


def categorized_finance_response(category: str) -> ResponseFactory:
    def _response(
        messages: list[Msg],
        _tools: list[dict] | None,
        _call_index: int,
    ) -> ChatResponse:
        evidence_ids = evidence_ids_from_messages(messages)
        payload = scout_payload(AgentRole.FINANCE_SCOUT, evidence_ids)
        payload["candidate_drafts"][0]["category"] = category
        payload["candidate_drafts"][0]["signal_status"] = "confirmed_fact"
        return ChatResponse(
            content=[TextBlock(text=json.dumps(payload, ensure_ascii=False))],
            is_last=True,
        )

    return _response


def confirmed_event_finance_response(
    messages: list[Msg],
    tools: list[dict] | None,
    call_index: int,
) -> ChatResponse:
    return categorized_finance_response("confirmed_event")(messages, tools, call_index)


def official_response_without_followups(
    messages: list[Msg],
    _tools: list[dict] | None,
    _call_index: int,
) -> ChatResponse:
    evidence_ids = evidence_ids_from_messages(messages)
    payload = scout_payload(AgentRole.OFFICIAL_SCOUT, evidence_ids)
    payload["candidate_drafts"][0]["followup_questions"] = []
    return ChatResponse(
        content=[TextBlock(text=json.dumps(payload, ensure_ascii=False))],
        is_last=True,
    )


def categorized_official_response(category: str) -> ResponseFactory:
    def _response(
        messages: list[Msg],
        _tools: list[dict] | None,
        _call_index: int,
    ) -> ChatResponse:
        evidence_ids = evidence_ids_from_messages(messages)
        payload = scout_payload(AgentRole.OFFICIAL_SCOUT, evidence_ids)
        payload["candidate_drafts"][0]["category"] = category
        return ChatResponse(
            content=[TextBlock(text=json.dumps(payload, ensure_ascii=False))],
            is_last=True,
        )

    return _response


def test_all_scouts_create_materialized_items_and_pass_collect_gate(db_session) -> None:
    tool_registry = create_default_tool_registry()
    role_registry = create_default_agent_role_registry(tool_registry)
    task_factory = ScoutTaskFactory()
    models = {
        role: ScriptedScoutModel(role, [manual_seed_tool_call(role), final_scout_response(role)])
        for role in {profile.role for profile in task_factory.profiles.list_profiles()}
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
        config=HarnessConfig(min_selected_items=5),
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
            RunPhase.SCOUTING: task_factory.create_all_tasks(objective=fixture.objective)
        },
    )

    evidence = EvidenceRepository(db_session).list_by_run(RUN_ID)
    candidates = CandidateRepository(db_session).list_by_run(RUN_ID)
    clusters = EventClusterRepository(db_session).list_by_run(RUN_ID)
    evaluations = EvaluationRepository(db_session).list_by_run(RUN_ID)
    persisted_run = RunRepository(db_session).require(RUN_ID)

    assert next_run.phase == RunPhase.WRITING
    assert decisions[-1].outcome == "enter_writing"
    assert len(evidence) == 5
    assert len(candidates) == 5
    assert len(clusters) == 5
    assert len(evaluations) == 5
    assert {candidate.created_by_agent for candidate in candidates} == {
        AgentRole.SOCIAL_SCOUT,
        AgentRole.CODE_MODEL_SCOUT,
        AgentRole.RESEARCH_SCOUT,
        AgentRole.OFFICIAL_SCOUT,
        AgentRole.FINANCE_SCOUT,
    }
    assert {candidate.metadata["scout_profile"] for candidate in candidates} == {
        candidate.created_by_agent.value for candidate in candidates
    }
    assert persisted_run.selected_cluster_ids == [cluster.id for cluster in clusters]

    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)
    event_types = [event.event_type for event in timeline.events]
    assert event_types.count(TraceEventType.TOOL_CALL_COMPLETED) == 5
    assert event_types.count(TraceEventType.CANDIDATE_CREATED) == 5
    assert event_types.count(TraceEventType.CLUSTER_CREATED) == 5
    assert event_types.count(TraceEventType.EVALUATION_CREATED) == 5


@pytest.mark.parametrize(
    "category",
    ["confirmed_event", "other", "watchlist_update", "early_signal"],
)
def test_materializer_normalizes_finance_categories_to_tech_finance(
    db_session,
    category,
) -> None:
    tool_registry = create_default_tool_registry()
    role_registry = create_default_agent_role_registry(tool_registry)
    model = ScriptedScoutModel(
        AgentRole.FINANCE_SCOUT,
        [manual_seed_tool_call(AgentRole.FINANCE_SCOUT), categorized_finance_response(category)],
    )
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
        budgets=RunBudgets(max_collect_rounds=1),
    )

    CollectLoopHarness(daily_harness.context).run(
        run,
        tasks_by_phase={
            RunPhase.SCOUTING: [
                ScoutTaskFactory().create_task(
                    AgentRole.FINANCE_SCOUT,
                    objective=fixture.objective,
                )
            ]
        },
    )

    candidates = CandidateRepository(db_session).list_by_run(RUN_ID)
    assert len(candidates) == 1
    assert candidates[0].category == "tech_finance"
    assert candidates[0].metadata["normalized_category_from"] == category


def test_materializer_adds_default_followup_for_official_scout(db_session) -> None:
    tool_registry = create_default_tool_registry()
    role_registry = create_default_agent_role_registry(tool_registry)
    model = ScriptedScoutModel(
        AgentRole.OFFICIAL_SCOUT,
        [manual_seed_tool_call(AgentRole.OFFICIAL_SCOUT), official_response_without_followups],
    )
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
        budgets=RunBudgets(max_collect_rounds=1),
    )

    CollectLoopHarness(daily_harness.context).run(
        run,
        tasks_by_phase={
            RunPhase.SCOUTING: [
                ScoutTaskFactory().create_task(
                    AgentRole.OFFICIAL_SCOUT,
                    objective=fixture.objective,
                )
            ]
        },
    )

    candidates = CandidateRepository(db_session).list_by_run(RUN_ID)
    assert len(candidates) == 1
    assert candidates[0].followup_questions
    assert candidates[0].metadata["normalized_missing_followup_questions"] is True


def test_materializer_normalizes_official_categories_to_official_update(db_session) -> None:
    tool_registry = create_default_tool_registry()
    role_registry = create_default_agent_role_registry(tool_registry)
    model = ScriptedScoutModel(
        AgentRole.OFFICIAL_SCOUT,
        [manual_seed_tool_call(AgentRole.OFFICIAL_SCOUT), categorized_official_response("tech_finance")],
    )
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
        budgets=RunBudgets(max_collect_rounds=1),
    )

    CollectLoopHarness(daily_harness.context).run(
        run,
        tasks_by_phase={
            RunPhase.SCOUTING: [
                ScoutTaskFactory().create_task(
                    AgentRole.OFFICIAL_SCOUT,
                    objective=fixture.objective,
                )
            ]
        },
    )

    candidates = CandidateRepository(db_session).list_by_run(RUN_ID)
    assert len(candidates) == 1
    assert candidates[0].category == "official_update"
    assert candidates[0].metadata["normalized_category_from"] == "tech_finance"


def test_materializer_rejects_scout_output_that_violates_profile(db_session) -> None:
    tool_registry = create_default_tool_registry()
    role_registry = create_default_agent_role_registry(tool_registry)
    model = ScriptedScoutModel(AgentRole.FINANCE_SCOUT, [invalid_finance_response])
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
        budgets=RunBudgets(max_collect_rounds=1),
    )

    with pytest.raises(HarnessError, match="finance_scout candidate drafts require tickers or potential_impact"):
        CollectLoopHarness(daily_harness.context).run(
            run,
            tasks_by_phase={
                RunPhase.SCOUTING: [
                    ScoutTaskFactory().create_task(
                        AgentRole.FINANCE_SCOUT,
                        objective=fixture.objective,
                    )
                ]
            },
        )
