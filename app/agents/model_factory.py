"""Model factory that wires AgentScope ChatModel instances to Connor config."""

from __future__ import annotations

from collections.abc import Callable

from agentscope.credential import DeepSeekCredential
from agentscope.model import ChatModelBase, DeepSeekChatModel
from pydantic import SecretStr

from app.agents.config import AgentRoleConfig
from app.config import get_settings


def create_deepseek_model_factory() -> Callable[[AgentRoleConfig], ChatModelBase]:
    """Return a callable that builds DeepSeekChatModel per role.

    Reads credentials from the Connor Settings singleton so API keys stay
    out of agent role configuration objects.
    """

    settings = get_settings()
    api_key = settings.deepseek_api_key
    if not api_key:
        raise RuntimeError(
            "CONNOR_DEEPSEEK_API_KEY is not set. "
            "Set the environment variable or configure a .env file."
        )

    credential = DeepSeekCredential(
        id="connor-deepseek",
        name="Connor.ai DeepSeek Provider",
        api_key=SecretStr(api_key),
        base_url=settings.deepseek_base_url,
    )

    def factory(config: AgentRoleConfig) -> ChatModelBase:
        model_name = config.execution.model_name or settings.deepseek_model
        temperature = config.execution.temperature
        params: dict = {}
        if temperature is not None:
            params["temperature"] = temperature
        client_kwargs = {}
        if config.execution.timeout_seconds is not None:
            client_kwargs["timeout"] = float(config.execution.timeout_seconds)
        return DeepSeekChatModel(
            credential=credential,
            model=model_name,
            parameters=DeepSeekChatModel.Parameters(**params) if params else None,
            stream=False,
            max_retries=2,
            retry_delay=2.0,
            client_kwargs=client_kwargs,
        )

    return factory
