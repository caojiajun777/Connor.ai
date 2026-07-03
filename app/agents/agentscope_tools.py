"""AgentScope Toolkit bridge for Connor.ai tools."""

from __future__ import annotations

import json
from typing import Any

from agentscope.message import TextBlock, ToolResultState
from agentscope.permission import PermissionBehavior, PermissionDecision
from agentscope.tool import FunctionTool, ToolChunk, Toolkit

from app.domain import AgentRole, RunPhase, ToolCallStatus
from app.tools import ToolExecutionContext, ToolExecutionResult, ToolExecutor, ToolRegistry


class ConnorFunctionTool(FunctionTool):
    """AgentScope function tool that delegates execution policy to Connor.ai."""

    async def check_permissions(self, *_args: Any, **_kwargs: Any) -> PermissionDecision:
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="Allowed by Connor.ai ToolRegistry role policy.",
        )


class AgentScopeToolBridge:
    """Build AgentScope toolkits that execute through Connor.ai ToolExecutor."""

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
        run_id: str,
        phase: RunPhase,
        agent_role: AgentRole,
    ):
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor
        self.run_id = run_id
        self.phase = phase
        self.agent_role = agent_role
        self.executed_results: list[ToolExecutionResult] = []

    def create_toolkit(self, allowed_tool_names: list[str]) -> Toolkit:
        """Create an AgentScope Toolkit containing only role-allowed tools."""

        tools = []
        for tool_name in allowed_tool_names:
            registered = self.tool_registry.require_allowed(tool_name, self.agent_role)
            spec = registered.spec
            tools.append(
                ConnorFunctionTool(
                    self._create_connor_tool(spec.name),
                    name=spec.name,
                    description=spec.description,
                    is_concurrency_safe=True,
                    is_read_only=False,
                )
            )

        return Toolkit(tools=tools)

    def _create_connor_tool(self, tool_name: str):
        def connor_tool(query: str, params: dict[str, Any] | None = None) -> ToolChunk:
            """Execute a Connor.ai tool and return traceable evidence IDs."""

            result = self.tool_executor.execute(
                tool_name=tool_name,
                context=ToolExecutionContext(
                    run_id=self.run_id,
                    phase=self.phase,
                    agent_role=self.agent_role,
                    query=query,
                    params=params or {},
                ),
            )
            self.executed_results.append(result)
            state = (
                ToolResultState.SUCCESS
                if result.tool_call.status == ToolCallStatus.SUCCEEDED
                else ToolResultState.ERROR
            )
            return ToolChunk(
                content=[
                    TextBlock(
                        text=json.dumps(
                            self._agent_visible_payload(result),
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                    )
                ],
                state=state,
            )

        return connor_tool

    @staticmethod
    def _agent_visible_payload(result: ToolExecutionResult) -> dict[str, Any]:
        return {
            "tool_name": result.spec.name,
            "status": result.tool_call.status.value,
            "query": result.envelope.query,
            "tool_call_id": result.tool_call.id,
            "trace_event_id": result.trace_event.id,
            "evidence_ids": [item.id for item in result.evidence_items],
            "items": [
                {
                    "title": item.title,
                    "url": str(item.url) if item.url is not None else None,
                    "snippet": item.snippet,
                    "source_type": item.source_type.value,
                    "source_name": item.source_name,
                    "evidence_id": item.id,
                }
                for item in result.evidence_items
            ],
            "errors": [error.model_dump(mode="json") for error in result.envelope.errors],
            "raw_artifact_ref": (
                result.envelope.raw_artifact_ref.model_dump(mode="json")
                if result.envelope.raw_artifact_ref is not None
                else None
            ),
            "metadata": result.envelope.metadata,
        }
