"""Agent role configuration."""

from typing import Any

from pydantic import BaseModel, Field

from app.agents.outputs import AgentStructuredOutput
from app.domain import AgentRole


class AgentExecutionConfig(BaseModel):
    """AgentScope execution limits and model hints for one agent role."""

    max_iters: int = Field(default=3, gt=0)
    max_tool_calls: int = Field(default=5, ge=0)
    timeout_seconds: int | None = Field(default=None, gt=0)
    model_name: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRoleConfig(BaseModel):
    """Static role configuration for a Connor.ai agent."""

    role: AgentRole
    display_name: str
    system_prompt: str
    allowed_tool_names: list[str] = Field(default_factory=list)
    output_model: type[AgentStructuredOutput] = AgentStructuredOutput
    execution: AgentExecutionConfig = Field(default_factory=AgentExecutionConfig)

    model_config = {"arbitrary_types_allowed": True}
