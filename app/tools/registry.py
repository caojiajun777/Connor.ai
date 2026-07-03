"""Tool registry with role-based access control."""

from app.domain import AgentRole
from app.tools.base import RegisteredTool, ToolExecutionError, ToolFunction, ToolSpec


class ToolRegistry:
    """Register tools and expose role-filtered tool sets."""

    def __init__(self):
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, spec: ToolSpec, func: ToolFunction) -> RegisteredTool:
        if spec.name in self._tools:
            raise ToolExecutionError(f"tool already registered: {spec.name}")
        if not spec.allowed_agent_roles:
            raise ToolExecutionError(f"tool {spec.name} must allow at least one agent role")
        registered = RegisteredTool(spec=spec, func=func)
        self._tools[spec.name] = registered
        return registered

    def get(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def require(self, name: str) -> RegisteredTool:
        tool = self.get(name)
        if tool is None:
            raise ToolExecutionError(f"unknown tool: {name}")
        return tool

    def require_allowed(self, name: str, agent_role: AgentRole) -> RegisteredTool:
        tool = self.require(name)
        if not tool.spec.allows(agent_role):
            raise ToolExecutionError(f"agent role {agent_role.value} cannot use tool {name}")
        return tool

    def list_tools(self) -> list[ToolSpec]:
        return [registered.spec for registered in self._tools.values()]

    def list_for_agent(self, agent_role: AgentRole) -> list[ToolSpec]:
        return [
            registered.spec
            for registered in self._tools.values()
            if registered.spec.allows(agent_role)
        ]

