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
from app.agents.config import AgentRoleConfig
from app.domain import AgentRole, RunPhase, TraceEventType
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


def tool_call_response() -> ChatResponse:
    return ChatResponse(
        content=[
            ToolCallBlock(
                id="tool_call_manual_seed_1",
                name="manual_seed",
                input=json.dumps(
                    {
                        "query": "seed OpenAI reasoning API signal",
                        "params": {
                            "retrieved_at": BASE_TIME.isoformat(),
                            "items": [
                                {
                                    "title": "Manual OpenAI reasoning API signal",
                                    "url": "https://example.com/openai-reasoning",
                                    "snippet": (
                                        "Manually seeded signal about possible "
                                        "reasoning controls."
                                    ),
                                    "raw_hash": "sha256:agent-manual",
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


def test_agent_runner_rejects_invalid_structured_output_and_records_error(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    model = ScriptedAgentScopeModel(
        [
            ChatResponse(
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
        ]
    )
    runner = create_runner(db_session, model)

    with pytest.raises(ValidationError):
        runner.run(
            AgentRunRequest(
                run_id=RUN_ID,
                phase=RunPhase.SCOUTING,
                agent_role=AgentRole.SOCIAL_SCOUT,
                task="Return invalid scout output.",
            )
        )

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
