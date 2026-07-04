"""Agent role registry."""

from app.agents.config import AgentExecutionConfig, AgentRoleConfig
from app.agents.outputs import (
    AgentStructuredOutput,
    ClustererOutput,
    EditorOutput,
    EvaluatorOutput,
    ReviewerOutput,
    ScoutOutput,
    WatchlistAgentOutput,
    WriterOutput,
)
from app.agents.prompts import ROLE_PROMPTS
from app.domain import AgentRole
from app.evaluators.profiles import create_default_evaluator_profile_registry
from app.scouts.profiles import create_default_scout_profile_registry
from app.watchlist.tasks import watchlist_prompt_extension
from app.tools import ToolRegistry


SCOUT_ROLES = {
    AgentRole.SOCIAL_SCOUT,
    AgentRole.CODE_MODEL_SCOUT,
    AgentRole.RESEARCH_SCOUT,
    AgentRole.OFFICIAL_SCOUT,
    AgentRole.FINANCE_SCOUT,
}

EVALUATOR_ROLES = {
    AgentRole.FRONTIER_EVALUATOR,
    AgentRole.EVENT_EVALUATOR,
    AgentRole.MARKET_EVALUATOR,
}


class AgentRoleRegistry:
    """Stores role-level agent configuration."""

    def __init__(self):
        self._configs: dict[AgentRole, AgentRoleConfig] = {}

    def register(self, config: AgentRoleConfig) -> AgentRoleConfig:
        if config.role in self._configs:
            raise ValueError(f"agent role already registered: {config.role.value}")
        self._configs[config.role] = config
        return config

    def require(self, role: AgentRole) -> AgentRoleConfig:
        config = self._configs.get(role)
        if config is None:
            raise ValueError(f"agent role not registered: {role.value}")
        return config

    def list_configs(self) -> list[AgentRoleConfig]:
        return list(self._configs.values())


def create_default_agent_role_registry(tool_registry: ToolRegistry) -> AgentRoleRegistry:
    """Create role configs using registered tool permissions."""

    registry = AgentRoleRegistry()
    scout_profiles = create_default_scout_profile_registry()
    evaluator_profiles = create_default_evaluator_profile_registry()
    for role in AgentRole:
        if role == AgentRole.SYSTEM:
            continue
        output_model: type[AgentStructuredOutput]
        if role in SCOUT_ROLES:
            output_model = ScoutOutput
        elif role == AgentRole.CLUSTERER:
            output_model = ClustererOutput
        elif role in EVALUATOR_ROLES:
            output_model = EvaluatorOutput
        elif role == AgentRole.WATCHLIST_AGENT:
            output_model = WatchlistAgentOutput
        elif role == AgentRole.WRITER:
            output_model = WriterOutput
        elif role == AgentRole.REVIEWER:
            output_model = ReviewerOutput
        elif role == AgentRole.EDITOR:
            output_model = EditorOutput
        else:
            output_model = AgentStructuredOutput

        system_prompt = ROLE_PROMPTS[role]
        if role in SCOUT_ROLES:
            system_prompt = f"{system_prompt}\n\n{scout_profiles.require(role).prompt_extension()}"
        if role in EVALUATOR_ROLES:
            system_prompt = (
                f"{system_prompt}\n\n{evaluator_profiles.require(role).prompt_extension()}"
            )
        if role == AgentRole.WATCHLIST_AGENT:
            system_prompt = f"{system_prompt}\n\n{watchlist_prompt_extension()}"

        registry.register(
            AgentRoleConfig(
                role=role,
                display_name=role.value.replace("_", " ").title(),
                system_prompt=system_prompt,
                allowed_tool_names=[
                    spec.name for spec in tool_registry.list_for_agent(role)
                ],
                output_model=output_model,
                execution=AgentExecutionConfig(),
            )
        )
    return registry
