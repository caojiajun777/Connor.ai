"""Model factory tests."""

from agentscope.model import DeepSeekChatModel

from app.agents.config import AgentExecutionConfig, AgentRoleConfig
from app.agents.model_factory import create_deepseek_model_factory
from app.agents.outputs import ScoutOutput
from app.config import get_settings
from app.domain import AgentRole


def test_deepseek_model_factory_applies_role_timeout_to_client(monkeypatch) -> None:
    monkeypatch.setenv("CONNOR_DEEPSEEK_API_KEY", "test-key")
    get_settings.cache_clear()
    try:
        factory = create_deepseek_model_factory()
        model = factory(
            AgentRoleConfig(
                role=AgentRole.SOCIAL_SCOUT,
                display_name="Social Scout",
                system_prompt="Test",
                output_model=ScoutOutput,
                execution=AgentExecutionConfig(timeout_seconds=33),
            )
        )
    finally:
        get_settings.cache_clear()

    assert isinstance(model, DeepSeekChatModel)
    assert model.client_kwargs["timeout"] == 33.0
    assert model.stream is False
