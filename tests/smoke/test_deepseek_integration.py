"""Smoke tests for DeepSeek API integration through AgentScope.

Run with the API key set in .env or CONNOR_DEEPSEEK_API_KEY:
  python -m pytest tests/smoke/test_deepseek_integration.py -v
"""

import pytest

from app.agents import (
    AgentRunRequest,
    AgentRunner,
    create_deepseek_model_factory,
    create_default_agent_role_registry,
)
from app.agents.config import AgentExecutionConfig, AgentRoleConfig
from app.agents.outputs import ScoutOutput
from app.config import get_settings
from app.domain import AgentRole, RunPhase
from app.tools import create_default_tool_registry

_has_api_key: bool | None = None


def _check_api_key() -> bool:
    global _has_api_key
    if _has_api_key is None:
        _has_api_key = bool(get_settings().deepseek_api_key)
    return _has_api_key


pytestmark = pytest.mark.skipif(
    not _check_api_key(),
    reason="CONNOR_DEEPSEEK_API_KEY not set; provide it to run the DeepSeek smoke test",
)


def test_deepseek_model_responds_to_prompt():
    """DeepSeek model should respond to a simple text prompt via AgentScope."""

    import asyncio

    from agentscope.message import UserMsg

    factory = create_deepseek_model_factory()
    config = AgentRoleConfig(
        role=AgentRole.SOCIAL_SCOUT,
        display_name="Smoke Test",
        system_prompt="You are a helpful assistant. Reply concisely.",
        allowed_tool_names=[],
        output_model=ScoutOutput,
        execution=AgentExecutionConfig(max_iters=1, timeout_seconds=60),
    )

    model = factory(config)
    msg = UserMsg(name="test", content="Say 'hello world'")
    response = asyncio.run(model.__call__([msg]))
    assert response is not None
    text = str(response)
    assert len(text) > 0
    print(f"DeepSeek response: {text[:200]}")


def test_agent_runner_full_roundtrip(db_session):
    """AgentRunner + DeepSeek should produce a validated ScoutOutput."""

    tool_registry = create_default_tool_registry()
    role_registry = create_default_agent_role_registry(tool_registry)
    model_factory = create_deepseek_model_factory()

    runner = AgentRunner(
        session=db_session,
        role_registry=role_registry,
        tool_registry=tool_registry,
        model_factory=model_factory,
    )

    result = runner.run(
        AgentRunRequest(
            run_id="smoke-test-run",
            phase=RunPhase.SCOUTING,
            agent_role=AgentRole.SOCIAL_SCOUT,
            task=(
                "You are a data extraction agent. Your ONLY job is to return "
                "a single JSON object with this exact structure:\n"
                "{\n"
                '  "summary": "smoke test passed",\n'
                '  "candidate_drafts": [],\n'
                '  "evidence_ids": [],\n'
                '  "candidate_ids": [],\n'
                '  "followup_queries": ["deepseek-integration-verified"]\n'
                "}\n"
                "Do NOT call any tools. Do NOT add extra fields. "
                "Do NOT wrap the JSON in markdown fences. "
                "Return ONLY the JSON object, nothing else."
            ),
            context={"test": True, "no_tools": True},
        )
    )

    assert result.structured_output is not None
    assert isinstance(result.structured_output, ScoutOutput)
    assert result.structured_output.summary
    assert result.structured_output.followup_queries
