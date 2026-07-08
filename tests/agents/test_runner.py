"""AgentScope-first AgentRunner tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import pytest
from agentscope.credential import CredentialBase
from agentscope.message import Msg, TextBlock, ToolCallBlock
from agentscope.model import ChatModelBase, ChatResponse
from pydantic import BaseModel, ValidationError

from app.agents import (
    AgentRunRequest,
    AgentRunner,
    AgentScopeExecutionError,
    AgentScopeToolBridge,
    create_default_agent_role_registry,
)
from app.domain import AgentRole, ReviewDecision, RunPhase, TraceEventType
from app.repositories import EvidenceRepository, RunRepository
from app.services import TraceService
from app.tools import ToolExecutor, create_default_tool_registry
from tests.domain.fixtures import BASE_TIME, RUN_ID, run_state_fixture


ResponseFactory = Callable[
    [list[Msg], list[dict] | None, int],
    ChatResponse,
]


class ScriptedAgentScopeModel(ChatModelBase):
    """AgentScope ChatModelBase test double with scripted responses."""

    class Parameters(BaseModel):
        pass

    def __init__(self, responses: list[ChatResponse | ResponseFactory]):
        super().__init__(
            credential=CredentialBase(name="test"),
            model="scripted-agentscope-model",
            parameters=self.Parameters(),
            stream=False,
            max_retries=0,
        )
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    async def _call_api(
        self,
        model_name: str,
        messages: list[Msg],
        tools: list[dict] | None = None,
        tool_choice: Any | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        self.calls.append(
            {
                "model_name": model_name,
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
                "kwargs": kwargs,
            }
        )
        response = self.responses.pop(0)
        if callable(response):
            return response(messages, tools, len(self.calls))
        return response


class SlowAgentScopeModel(ChatModelBase):
    """AgentScope model that intentionally exceeds the configured timeout."""

    class Parameters(BaseModel):
        pass

    def __init__(self):
        super().__init__(
            credential=CredentialBase(name="test"),
            model="slow-agentscope-model",
            parameters=self.Parameters(),
            stream=False,
            max_retries=0,
        )

    async def _call_api(
        self,
        model_name: str,
        messages: list[Msg],
        tools: list[dict] | None = None,
        tool_choice: Any | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        await asyncio.sleep(0.05)
        return ChatResponse(
            content=[TextBlock(text=json.dumps({"summary": "Too late"}))],
            is_last=True,
        )


class EmptyMessageError(Exception):
    """Exception whose string representation is empty."""

    def __str__(self) -> str:
        return ""


class EmptyFailureAgentScopeModel(ChatModelBase):
    """AgentScope model that fails with an empty exception message."""

    class Parameters(BaseModel):
        pass

    def __init__(self):
        super().__init__(
            credential=CredentialBase(name="test"),
            model="empty-failure-agentscope-model",
            parameters=self.Parameters(),
            stream=False,
            max_retries=0,
        )

    async def _call_api(
        self,
        model_name: str,
        messages: list[Msg],
        tools: list[dict] | None = None,
        tool_choice: Any | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        raise EmptyMessageError()


def create_runner(db_session, model: ChatModelBase) -> AgentRunner:
    tool_registry = create_default_tool_registry()
    role_registry = create_default_agent_role_registry(tool_registry)
    return AgentRunner(
        db_session,
        role_registry=role_registry,
        tool_registry=tool_registry,
        model_factory=lambda _config: model,
    )


def tool_call_response(
    *,
    call_id: str = "tool_call_manual_seed_1",
    query: str = "seed OpenAI reasoning API signal",
    title: str = "Manual OpenAI reasoning API signal",
    raw_hash: str = "sha256:agent-manual",
) -> ChatResponse:
    return ChatResponse(
        content=[
            ToolCallBlock(
                id=call_id,
                name="manual_seed",
                input=json.dumps(
                    {
                        "query": query,
                        "params": {
                            "retrieved_at": BASE_TIME.isoformat(),
                            "items": [
                                {
                                    "title": title,
                                    "url": "https://example.com/openai-reasoning",
                                    "snippet": (
                                        "Manually seeded signal about possible "
                                        "reasoning controls."
                                    ),
                                    "raw_hash": raw_hash,
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


def final_scout_response(
    messages: list[Msg],
    _tools: list[dict] | None,
    _call_index: int,
) -> ChatResponse:
    evidence_ids = []
    for message in messages:
        for block in message.get_content_blocks():
            if getattr(block, "type", None) != "tool_result":
                continue
            if isinstance(block.output, str):
                text = block.output
            else:
                text = "".join(
                    item.text for item in block.output if isinstance(item, TextBlock)
                )
            evidence_ids.extend(json.loads(text)["evidence_ids"])

    return ChatResponse(
        content=[
            TextBlock(
                text=json.dumps(
                    {
                        "summary": "Found one manually seeded OpenAI API signal.",
                        "reasoning_summary": "The signal is specific enough to track.",
                        "evidence_ids": evidence_ids,
                        "followup_queries": ["Check official docs."],
                    },
                    ensure_ascii=False,
                )
            )
        ],
        is_last=True,
    )


def finalization_response_from_payload(
    messages: list[Msg],
    tools: list[dict] | None,
    _call_index: int,
) -> ChatResponse:
    assert not tools
    payload = json.loads(messages[-1].get_text_content())
    evidence_ids = payload["available_evidence_ids"]
    return ChatResponse(
        content=[
            TextBlock(
                text=json.dumps(
                    {
                        "summary": "Finalized from already collected tool evidence.",
                        "reasoning_summary": (
                            "The ReAct loop hit its iteration limit, so the final "
                            "answer was composed from existing tool evidence."
                        ),
                        "evidence_ids": evidence_ids,
                        "followup_queries": ["Check official docs."],
                    },
                    ensure_ascii=False,
                )
            )
        ],
        is_last=True,
    )


def test_agent_runner_uses_agentscope_tool_loop_and_traces_output(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    model = ScriptedAgentScopeModel([tool_call_response(), final_scout_response])
    runner = create_runner(db_session, model)

    result = runner.run(
        AgentRunRequest(
            run_id=RUN_ID,
            phase=RunPhase.SCOUTING,
            agent_role=AgentRole.SOCIAL_SCOUT,
            task="Find early OpenAI API signals.",
            context={"date": "2026-07-03"},
        )
    )
    db_session.commit()

    assert result.start_trace_event is not None
    assert result.completion_trace_event is not None
    assert result.structured_output.summary.startswith("Found one")
    assert len(result.tool_results) == 1
    assert len(model.calls) == 2

    first_call_tools = model.calls[0]["tools"]
    assert first_call_tools[0]["function"]["name"] == "manual_seed"

    evidence_id = result.tool_results[0].evidence_items[0].id
    assert result.structured_output.evidence_ids == [evidence_id]
    evidence = EvidenceRepository(db_session).require(evidence_id)
    assert evidence.title == "Manual OpenAI reasoning API signal"

    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)
    assert [event.event_type for event in timeline.events] == [
        TraceEventType.AGENT_STARTED,
        TraceEventType.TOOL_CALL_COMPLETED,
        TraceEventType.EVIDENCE_CREATED,
        TraceEventType.AGENT_COMPLETED,
    ]


def test_agent_runner_uses_scout_fallback_after_react_iteration_limit(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    max_iters_response = ChatResponse(
        content=[
            TextBlock(
                text=(
                    "Executed maximum iterations of reasoning-acting loop "
                    "without finishing."
                )
            )
        ],
        is_last=True,
    )
    model = ScriptedAgentScopeModel(
        [
            tool_call_response(
                call_id="tool_call_manual_seed_1",
                query="first code signal",
                title="First code signal",
                raw_hash="sha256:agent-manual-1",
            ),
            max_iters_response,
        ]
    )
    tool_registry = create_default_tool_registry()
    role_registry = create_default_agent_role_registry(tool_registry)
    role_registry.require(AgentRole.SOCIAL_SCOUT).execution.max_iters = 2
    runner = AgentRunner(
        db_session,
        role_registry=role_registry,
        tool_registry=tool_registry,
        model_factory=lambda _config: model,
    )

    result = runner.run(
        AgentRunRequest(
            run_id=RUN_ID,
            phase=RunPhase.SCOUTING,
            agent_role=AgentRole.SOCIAL_SCOUT,
            task="Keep calling tools until the ReAct loop reaches max_iters.",
            context={"date": "2026-07-03"},
        )
    )
    db_session.commit()

    assert result.structured_output.summary.startswith("Deterministically created")
    assert len(result.tool_results) == 1
    assert len(result.structured_output.evidence_ids) == 1
    assert len(result.structured_output.candidate_drafts) == 1
    assert len(model.calls) == 2
    assert result.completion_trace_event is not None
    assert result.completion_trace_event.metadata["react_max_iters_repaired"] is True
    assert result.completion_trace_event.metadata["deterministic_structured_fallback"] is True

    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)
    assert [event.event_type for event in timeline.events] == [
        TraceEventType.AGENT_STARTED,
        TraceEventType.TOOL_CALL_COMPLETED,
        TraceEventType.EVIDENCE_CREATED,
        TraceEventType.AGENT_DECISION,
        TraceEventType.AGENT_COMPLETED,
    ]
    assert timeline.events[-2].metadata["repair_mode"] == "deterministic_scout_fallback"


def test_agent_runner_moves_extra_nested_output_fields_to_metadata(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    model = ScriptedAgentScopeModel(
        [
            ChatResponse(
                content=[
                    TextBlock(
                        text=json.dumps(
                            {
                                "summary": "Clustered one candidate.",
                                "reasoning_summary": "The candidate is already canonical.",
                                "cluster_drafts": [
                                    {
                                        "category": "early_signal",
                                        "title": "OpenAI reasoning API signal",
                                        "canonical_claim": (
                                            "A candidate suggests OpenAI may be testing "
                                            "a reasoning API option."
                                        ),
                                        "candidate_ids": ["cand_openai_reasoning"],
                                        "evidence_ids": ["ev_openai_reasoning"],
                                        "evidence_strength": "moderate",
                                    }
                                ],
                            },
                            ensure_ascii=False,
                        )
                    )
                ],
                is_last=True,
            )
        ]
    )
    runner = create_runner(db_session, model)

    result = runner.run(
        AgentRunRequest(
            run_id=RUN_ID,
            phase=RunPhase.CLUSTERING,
            agent_role=AgentRole.CLUSTERER,
            task="Cluster candidate drafts.",
        )
    )

    draft = result.structured_output.cluster_drafts[0]
    assert draft.metadata["extra_fields"]["evidence_strength"] == "moderate"


def test_agent_runner_repairs_malformed_structured_output_once(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    model = ScriptedAgentScopeModel(
        [
            ChatResponse(
                content=[
                    TextBlock(
                        text='{"summary": "Truncated cluster output", "cluster_drafts": ['
                    )
                ],
                is_last=True,
            ),
            final_clusterer_repair_response,
        ]
    )
    runner = create_runner(db_session, model)

    result = runner.run(
        AgentRunRequest(
            run_id=RUN_ID,
            phase=RunPhase.CLUSTERING,
            agent_role=AgentRole.CLUSTERER,
            task="Cluster candidate drafts.",
        )
    )

    assert result.structured_output.summary == "Repaired cluster output."
    assert len(result.structured_output.cluster_drafts) == 1
    assert len(model.calls) == 2
    assert model.calls[-1]["tools"] == []
    assert result.completion_trace_event is not None
    assert result.completion_trace_event.metadata["structured_output_repaired"] is True


def test_agent_runner_uses_clusterer_fallback_after_failed_repair(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    malformed_response = ChatResponse(
        content=[TextBlock(text='{"summary": "Still truncated", "cluster_drafts": [')],
        is_last=True,
    )
    model = ScriptedAgentScopeModel([malformed_response, malformed_response])
    runner = create_runner(db_session, model)

    result = runner.run(
        AgentRunRequest(
            run_id=RUN_ID,
            phase=RunPhase.CLUSTERING,
            agent_role=AgentRole.CLUSTERER,
            task="Cluster candidate drafts.",
            context={
                "candidate_context": [
                    {
                        "id": "cand_openai_reasoning",
                        "category": "early_signal",
                        "claim_summary": "OpenAI may be testing a reasoning API option.",
                        "entities": ["OpenAI"],
                        "tickers": [],
                        "topics": ["api", "reasoning"],
                        "evidence_ids": ["ev_openai_reasoning"],
                    }
                ]
            },
        )
    )

    assert result.structured_output.metadata["deterministic_fallback"] is True
    assert len(result.structured_output.cluster_drafts) == 1
    assert result.structured_output.cluster_drafts[0].candidate_ids == ["cand_openai_reasoning"]
    assert result.completion_trace_event is not None
    assert result.completion_trace_event.metadata["deterministic_structured_fallback"] is True


def test_agent_runner_uses_clusterer_fallback_after_timeout(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    tool_registry = create_default_tool_registry()
    role_registry = create_default_agent_role_registry(tool_registry)
    role_registry.require(AgentRole.CLUSTERER).execution.timeout_seconds = 0.001
    runner = AgentRunner(
        db_session,
        role_registry=role_registry,
        tool_registry=tool_registry,
        model_factory=lambda _config: SlowAgentScopeModel(),
    )

    result = runner.run(
        AgentRunRequest(
            run_id=RUN_ID,
            phase=RunPhase.CLUSTERING,
            agent_role=AgentRole.CLUSTERER,
            task="Cluster candidate drafts.",
            context={
                "candidate_context": [
                    {
                        "id": "cand_openai_reasoning",
                        "category": "early_signal",
                        "claim_summary": "OpenAI may be testing a reasoning API option.",
                        "entities": ["OpenAI"],
                        "tickers": [],
                        "topics": ["api", "reasoning"],
                        "evidence_ids": ["ev_openai_reasoning"],
                    }
                ]
            },
        )
    )

    assert result.structured_output.metadata["deterministic_fallback"] is True
    assert result.structured_output.cluster_drafts[0].candidate_ids == ["cand_openai_reasoning"]
    assert result.completion_trace_event is not None
    assert result.completion_trace_event.metadata["timeout_fallback"] is True
    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)
    assert any(event.event_type == TraceEventType.ERROR for event in timeline.events)


def test_agent_runner_uses_writer_fallback_after_failed_repair(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    malformed_response = ChatResponse(
        content=[TextBlock(text='{"summary": "Still truncated", "report_drafts": [')],
        is_last=True,
    )
    model = ScriptedAgentScopeModel([malformed_response, malformed_response])
    runner = create_runner(db_session, model)

    result = runner.run(
        AgentRunRequest(
            run_id=RUN_ID,
            phase=RunPhase.WRITING,
            agent_role=AgentRole.WRITER,
            task="Write report.",
            context={
                "report_date": "2026-07-03",
                "writing_context": {
                    "selected_clusters": [
                        {
                            "id": "cl_openai_reasoning_api",
                            "category": "early_signal",
                            "report_bucket": "early_signals",
                            "write_policy": "write_now",
                            "title": "OpenAI reasoning API signal",
                            "canonical_claim": (
                                "OpenAI may be testing a reasoning-control API option."
                            ),
                            "evidence_ids": [
                                "ev_openai_hn_reasoning",
                                "ev_openai_wrapper_commit",
                            ],
                            "tickers": [],
                            "topics": ["api", "reasoning"],
                            "evaluation_decisions": ["select_early_signal"],
                            "required_followups": ["Check official docs."],
                            "missing_evidence": [],
                        }
                    ]
                },
            },
        )
    )

    output = result.structured_output
    draft = output.report_drafts[0]
    item = draft.sections[0].items[0]
    assert output.metadata["deterministic_fallback"] is True
    assert draft.metadata["deterministic_fallback"] is True
    assert item.cluster_ids == ["cl_openai_reasoning_api"]
    assert item.evidence_ids == ["ev_openai_hn_reasoning", "ev_openai_wrapper_commit"]
    assert item.uncertainty_label == "unconfirmed; requires follow-up"
    assert result.completion_trace_event.metadata["deterministic_structured_fallback"] is True


def test_agent_runner_uses_editor_fallback_after_timeout(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    model = SlowAgentScopeModel()
    runner = create_runner(db_session, model)
    runner.role_registry.require(AgentRole.EDITOR).execution.timeout_seconds = 0.001

    result = runner.run(
        AgentRunRequest(
            run_id=RUN_ID,
            phase=RunPhase.EDITING,
            agent_role=AgentRole.EDITOR,
            task="Revise report.",
            context={
                "editor_context": {
                    "report": {
                        "id": "report_timeout_editor",
                        "title": "Connor.ai Daily Intelligence",
                        "sections": [
                            {
                                "section_id": "early_signals",
                                "title": "前沿爆料 Early Signals",
                                "items": [
                                    {
                                        "title": "OpenAI reasoning API signal",
                                        "category": "early_signal",
                                        "status_label": "未确认来源信号",
                                        "core_information": "社区信号显示 API 行为可能变化。",
                                        "why_it_matters": "这会影响 agent runtime 控制。",
                                        "evidence_ids": ["ev_openai_hn_reasoning"],
                                        "cluster_ids": ["cl_openai_reasoning_api"],
                                        "followup_points": ["检查官方文档。"],
                                        "uncertainty_label": "未确认",
                                    }
                                ],
                            }
                        ],
                        "watchlist_updates": [],
                        "full_json": {
                            "overview_judgments": ["API 线索仍需确认。"],
                            "tomorrow_focus": ["检查官方文档。"],
                        },
                    }
                }
            },
        )
    )

    output = result.structured_output
    draft = output.revised_report_drafts[0]
    assert output.metadata["deterministic_fallback"] is True
    assert draft.report_id == "report_timeout_editor"
    assert draft.metadata["fallback_reason"] == "editor_timeout_or_repair_failure"
    assert result.completion_trace_event.metadata["timeout_fallback"] is True


def test_agent_runner_repairs_writer_item_evidence_from_context(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    model = ScriptedAgentScopeModel(
        [
            ChatResponse(
                content=[
                    TextBlock(
                        text=json.dumps(
                            {
                                "summary": "Drafted report with missing item evidence.",
                                "report_drafts": [
                                    {
                                        "title": "Connor.ai Daily Intelligence",
                                        "sections": [
                                            {
                                                "section_id": "early_signals",
                                                "title": "Early Signals",
                                                "items": [
                                                    {
                                                        "title": "OpenAI reasoning API signal",
                                                        "category": "early_signal",
                                                        "status_label": "Unconfirmed signal",
                                                        "core_information": (
                                                            "A cluster points to a possible "
                                                            "reasoning API option."
                                                        ),
                                                        "why_it_matters": (
                                                            "It could affect agent runtime controls."
                                                        ),
                                                        "cluster_ids": ["cl_openai_reasoning_api"],
                                                        "followup_points": ["Check official docs."],
                                                        "uncertainty_label": "unconfirmed",
                                                    }
                                                ],
                                            }
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
        ]
    )
    runner = create_runner(db_session, model)

    result = runner.run(
        AgentRunRequest(
            run_id=RUN_ID,
            phase=RunPhase.WRITING,
            agent_role=AgentRole.WRITER,
            task="Write report.",
            context={
                "writing_context": {
                    "selected_clusters": [
                        {
                            "id": "cl_openai_reasoning_api",
                            "evidence_ids": [
                                "ev_openai_hn_reasoning",
                                "ev_openai_wrapper_commit",
                            ],
                        }
                    ]
                }
            },
        )
    )

    item = result.structured_output.report_drafts[0].sections[0].items[0]
    assert item.evidence_ids == ["ev_openai_hn_reasoning", "ev_openai_wrapper_commit"]
    assert item.metadata["repaired_missing_evidence_ids"] is True


def test_agent_runner_normalizes_reviewer_pass_with_issues(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    model = ScriptedAgentScopeModel(
        [
            ChatResponse(
                content=[
                    TextBlock(
                        text=json.dumps(
                            {
                                "summary": "Reviewer found one concern but mislabeled pass.",
                                "decision": "pass",
                                "review_drafts": [
                                    {
                                        "decision": "pass",
                                        "reasoning_summary": "Evidence needs clearer linkage.",
                                        "issues": [
                                            {
                                                "priority": 2,
                                                "title": "Missing evidence chain",
                                                "body": "Add explicit evidence links.",
                                            }
                                        ],
                                        "required_changes": [],
                                    }
                                ],
                            },
                            ensure_ascii=False,
                        )
                    )
                ],
                is_last=True,
            )
        ]
    )
    runner = create_runner(db_session, model)

    result = runner.run(
        AgentRunRequest(
            run_id=RUN_ID,
            phase=RunPhase.REVIEWING,
            agent_role=AgentRole.REVIEWER,
            task="Review report.",
        )
    )

    output = result.structured_output
    assert output.decision == ReviewDecision.REVISE
    assert output.required_changes == ["Missing evidence chain"]
    assert output.review_drafts[0].decision == ReviewDecision.REVISE
    assert output.review_drafts[0].metadata["normalized_decision_from"] == "pass"


def test_agent_runner_normalizes_reviewer_issue_shape(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    model = ScriptedAgentScopeModel(
        [
            ChatResponse(
                content=[
                    TextBlock(
                        text=json.dumps(
                            {
                                "reasoning_summary": "Reviewer found malformed issues.",
                                "decision": "revise",
                                "review_drafts": [
                                    {
                                        "decision": "revise",
                                        "reasoning_summary": "One item needs better evidence.",
                                        "issues": [
                                            {
                                                "problem": "Weak evidence chain",
                                                "fix": "Add source-specific support.",
                                                "priority": "high",
                                            }
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
        ]
    )
    runner = create_runner(db_session, model)

    result = runner.run(
        AgentRunRequest(
            run_id=RUN_ID,
            phase=RunPhase.REVIEWING,
            agent_role=AgentRole.REVIEWER,
            task="Review report.",
        )
    )

    output = result.structured_output
    issue = output.review_drafts[0].issues[0]
    assert output.summary == "Reviewer requested revisions."
    assert output.decision == ReviewDecision.REVISE
    assert issue.priority == 1
    assert issue.title == "Weak evidence chain"
    assert issue.body == "Add source-specific support."
    assert issue.metadata["normalized_issue_shape"] is True


def test_agent_runner_normalizes_actionable_reviewer_reject_to_revise(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    model = ScriptedAgentScopeModel(
        [
            ChatResponse(
                content=[
                    TextBlock(
                        text=json.dumps(
                            {
                                "summary": "Reviewer rejected but asked for revision.",
                                "decision": "reject",
                                "review_drafts": [
                                    {
                                        "decision": "reject",
                                        "reasoning_summary": (
                                            "Report needs revision before publication."
                                        ),
                                        "issues": [
                                            {
                                                "priority": 1,
                                                "title": "Needs revision",
                                                "body": "Fix the status label.",
                                            }
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
        ]
    )
    runner = create_runner(db_session, model)

    result = runner.run(
        AgentRunRequest(
            run_id=RUN_ID,
            phase=RunPhase.REVIEWING,
            agent_role=AgentRole.REVIEWER,
            task="Review report.",
        )
    )

    output = result.structured_output
    assert output.decision == ReviewDecision.REVISE
    assert output.review_drafts[0].decision == ReviewDecision.REVISE
    assert output.metadata["normalized_decision_from"] == "reject"
    assert output.review_drafts[0].metadata["normalized_decision_from"] == "reject"


def final_clusterer_repair_response(
    messages: list[Msg],
    tools: list[dict] | None,
    _call_index: int,
) -> ChatResponse:
    assert not tools
    payload = json.loads(messages[-1].get_text_content())
    assert payload["context"]["structured_output_repair"] is True
    return ChatResponse(
        content=[
            TextBlock(
                text=json.dumps(
                    {
                        "summary": "Repaired cluster output.",
                        "reasoning_summary": "The repair produced one compact cluster.",
                        "cluster_drafts": [
                            {
                                "category": "early_signal",
                                "title": "OpenAI reasoning API signal",
                                "canonical_claim": (
                                    "A candidate suggests OpenAI may be testing "
                                    "a reasoning API option."
                                ),
                                "candidate_ids": ["cand_openai_reasoning"],
                                "evidence_ids": ["ev_openai_reasoning"],
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
            )
        ],
        is_last=True,
    )


def test_agent_runner_rejects_invalid_structured_output_and_records_error(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    invalid_response = ChatResponse(
        content=[
            TextBlock(
                text=json.dumps(
                    {
                        "summary": (
                            "Invalid because it has no evidence, "
                            "candidates, or followups."
                        )
                    }
                )
            )
        ],
        is_last=True,
    )
    model = ScriptedAgentScopeModel(
        [
            invalid_response,
            invalid_response,
        ]
    )
    runner = create_runner(db_session, model)

    with pytest.raises(AgentScopeExecutionError) as exc_info:
        runner.run(
            AgentRunRequest(
                run_id=RUN_ID,
                phase=RunPhase.SCOUTING,
                agent_role=AgentRole.SOCIAL_SCOUT,
                task="Return invalid scout output.",
            )
        )
    assert isinstance(exc_info.value.__cause__, ValidationError)

    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)
    assert timeline.events[-1].event_type == TraceEventType.ERROR


def test_agent_runner_timeout_records_non_empty_error(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    tool_registry = create_default_tool_registry()
    role_registry = create_default_agent_role_registry(tool_registry)
    role_registry.require(AgentRole.SOCIAL_SCOUT).execution.timeout_seconds = 0.001
    runner = AgentRunner(
        db_session,
        role_registry=role_registry,
        tool_registry=tool_registry,
        model_factory=lambda _config: SlowAgentScopeModel(),
    )

    with pytest.raises(AgentScopeExecutionError, match="timed out after"):
        runner.run(
            AgentRunRequest(
                run_id=RUN_ID,
                phase=RunPhase.SCOUTING,
                agent_role=AgentRole.SOCIAL_SCOUT,
                task="Timeout intentionally.",
            )
        )

    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)
    assert timeline.events[-1].event_type == TraceEventType.ERROR
    assert timeline.events[-1].error
    assert "timed out after" in timeline.events[-1].error


def test_agent_runner_empty_exception_records_non_empty_error(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    runner = create_runner(db_session, EmptyFailureAgentScopeModel())

    with pytest.raises(AgentScopeExecutionError, match="EmptyMessageError"):
        runner.run(
            AgentRunRequest(
                run_id=RUN_ID,
                phase=RunPhase.SCOUTING,
                agent_role=AgentRole.SOCIAL_SCOUT,
                task="Fail with empty exception message.",
            )
        )

    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)
    assert timeline.events[-1].event_type == TraceEventType.ERROR
    assert timeline.events[-1].error == "EmptyMessageError raised during AgentScope task."


def test_agentscope_tool_bridge_exposes_only_role_allowed_tools(db_session) -> None:
    tool_registry = create_default_tool_registry()
    role_registry = create_default_agent_role_registry(tool_registry)
    config = role_registry.require(AgentRole.REVIEWER)
    bridge = AgentScopeToolBridge(
        tool_registry=tool_registry,
        tool_executor=ToolExecutor(db_session, registry=tool_registry),
        run_id=RUN_ID,
        phase=RunPhase.REVIEWING,
        agent_role=AgentRole.REVIEWER,
    )

    toolkit = bridge.create_toolkit(config.allowed_tool_names)
    schemas = asyncio_run(toolkit.get_tool_schemas())
    tool_names = {schema["function"]["name"] for schema in schemas}

    assert "mock_search" in tool_names
    assert "manual_seed" not in tool_names


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)
