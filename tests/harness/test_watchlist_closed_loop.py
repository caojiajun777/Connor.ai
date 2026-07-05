"""Phase 11 Watchlist Agent closed-loop tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from agentscope.credential import CredentialBase
from agentscope.message import Msg, TextBlock
from agentscope.model import ChatModelBase, ChatResponse
from pydantic import BaseModel

from app.agents import AgentRunner, create_default_agent_role_registry
from app.domain import RunBudgets, RunPhase, TraceEventType
from app.harness import CollectLoopHarness, DailyRunHarness, HarnessConfig
from app.repositories import IntelligenceThreadRepository, WatchlistRepository
from app.services import TraceService
from app.tools import create_default_tool_registry
from app.watchlist import WatchlistTaskFactory
from tests.domain.fixtures import RUN_ID, early_signal_bundle, run_state_fixture
from tests.harness.helpers import persist_bundle


ResponseFactory = Callable[[list[Msg], list[dict] | None, int], ChatResponse]


class ScriptedPhase11Model(ChatModelBase):
    """AgentScope model that scripts one Watchlist Agent response."""

    class Parameters(BaseModel):
        pass

    def __init__(self, responses: list[ChatResponse | ResponseFactory]):
        super().__init__(
            credential=CredentialBase(name="test"),
            model="scripted-phase11-watchlist-agent",
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


def test_watchlist_agent_creates_memory_before_collect_gate(db_session) -> None:
    tool_registry = create_default_tool_registry()
    role_registry = create_default_agent_role_registry(tool_registry)
    model = ScriptedPhase11Model([final_watchlist_response])
    agent_runner = AgentRunner(
        db_session,
        role_registry=role_registry,
        tool_registry=tool_registry,
        model_factory=lambda _config: model,
    )
    daily_harness = DailyRunHarness(
        db_session,
        agent_runner=agent_runner,
        config=HarnessConfig(
            min_selected_items=1,
            auto_materialize_watchlist_from_evaluations=False,
        ),
    )
    fixture = run_state_fixture()
    run = daily_harness.create_run(
        run_id=RUN_ID,
        report_date=fixture.report_date,
        objective=fixture.objective,
        budgets=RunBudgets(max_collect_rounds=2),
    )
    persist_bundle(db_session, early_signal_bundle())

    next_run, decisions = CollectLoopHarness(daily_harness.context).run(
        run,
        tasks_by_phase={
            RunPhase.WATCHLIST_UPDATE: [
                WatchlistTaskFactory().create_task(objective=fixture.objective)
            ],
        },
    )

    watches = WatchlistRepository(db_session).list_by_run(RUN_ID)
    threads = IntelligenceThreadRepository(db_session).list_by_statuses(
        ["active", "dormant", "archived", "resolved"]
    )
    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)

    assert next_run.phase == RunPhase.WRITING
    assert decisions[-1].outcome == "enter_writing"
    assert len(watches) == 1
    assert watches[0].metadata["source_evaluation_id"] == "eval_openai_reasoning_frontier"
    assert len(threads) == 1
    assert TraceEventType.WATCHLIST_UPDATED in [event.event_type for event in timeline.events]
    assert TraceEventType.THREAD_UPDATED in [event.event_type for event in timeline.events]


def final_watchlist_response(
    messages: list[Msg],
    _tools: list[dict] | None,
    _call_index: int,
) -> ChatResponse:
    memory = memory_context_from_messages(messages)
    evaluation = memory["evaluations"][0]
    cluster = memory["clusters"][0]
    payload = {
        "summary": "Watchlist Agent opened a short watch.",
        "reasoning_summary": "The selected early signal is specific and needs short-term tracking.",
        "watchlist_drafts": [
            {
                "source_evaluation_id": evaluation["id"],
                "cluster_ids": [cluster["id"]],
                "topic": cluster["title"],
                "thesis": cluster["canonical_claim"],
                "watch_tier": "short",
                "priority": "high",
                "ttl_days": 7,
                "reactivation_rules": evaluation["required_followups"],
                "open_questions": evaluation["missing_evidence"],
                "entities": cluster["entities"],
                "topics": cluster["topics"],
                "evidence_ids": cluster["evidence_ids"],
            }
        ],
    }
    return ChatResponse(
        content=[TextBlock(text=json.dumps(payload, ensure_ascii=False))],
        is_last=True,
    )


def memory_context_from_messages(messages: list[Msg]) -> dict[str, Any]:
    for message in messages:
        text = message.get_text_content()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        context = payload.get("context", {})
        memory = context.get("memory_context")
        if isinstance(memory, dict):
            return memory
    return {}
