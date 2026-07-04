"""AgentScope-first runner for Connor.ai agents."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from agentscope.agent import Agent, ReActConfig
from agentscope.message import Msg, UserMsg
from agentscope.model import ChatModelBase
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agents.agentscope_tools import AgentScopeToolBridge
from app.agents.config import AgentRoleConfig
from app.agents.registry import AgentRoleRegistry
from app.agents.schemas import AgentRunRequest, AgentRunResult, AgentScopeExecutionError
from app.domain import TraceEventType, TraceStatus
from app.services import TraceService
from app.tools import ToolExecutor, ToolRegistry


AgentScopeModelFactory = Callable[[AgentRoleConfig], ChatModelBase]


class AgentRunner:
    """Run one Connor.ai role through an AgentScope Agent."""

    def __init__(
        self,
        session: Session,
        *,
        role_registry: AgentRoleRegistry,
        tool_registry: ToolRegistry,
        model_factory: AgentScopeModelFactory,
        trace_service: TraceService | None = None,
    ):
        self.session = session
        self.role_registry = role_registry
        self.tool_registry = tool_registry
        self.model_factory = model_factory
        self.trace_service = trace_service or TraceService(session)
        self.tool_executor = ToolExecutor(
            session,
            registry=tool_registry,
            trace_service=self.trace_service,
        )

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        """Synchronous wrapper for worker/test contexts without an event loop.

        NOTE: ``asyncio.run()`` must be called from the main thread on some platforms
        (Python 3.14+ enforces this on Windows). If this method is ever invoked from
        a worker thread, replace ``asyncio.run()`` with an explicit
        ``threading.Thread`` + ``new_event_loop()`` pattern, or migrate all callers to
        ``run_async()`` directly.
        """

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run_async(request))
        raise AgentScopeExecutionError(
            "AgentRunner.run() cannot be called from an active event loop; "
            "use AgentRunner.run_async() instead."
        )

    async def run_async(self, request: AgentRunRequest) -> AgentRunResult:
        """Run one AgentScope agent turn with Connor tracing and artifacts."""

        config = self.role_registry.require(request.agent_role)
        start_event = self.trace_service.record_event(
            run_id=request.run_id,
            phase=request.phase,
            agent_role=request.agent_role,
            event_type=TraceEventType.AGENT_STARTED,
            status=TraceStatus.STARTED,
            summary=f"{config.display_name} started AgentScope task.",
            input_payload={
                "task": request.task,
                "context": request.context,
                "allowed_tool_names": config.allowed_tool_names,
                "agentscope": True,
            },
        )

        bridge = AgentScopeToolBridge(
            tool_registry=self.tool_registry,
            tool_executor=self.tool_executor,
            run_id=request.run_id,
            phase=request.phase,
            agent_role=request.agent_role,
        )

        try:
            agent = self._create_agent(config, bridge)
            coro = agent.reply(self._build_user_message(request, config))
            if config.execution.timeout_seconds is not None:
                response = await asyncio.wait_for(coro, timeout=config.execution.timeout_seconds)
            else:
                response = await coro
            output_text = self._extract_text(response)
            structured_output = config.output_model.model_validate(
                self._extract_structured_payload(response, output_text)
            )
            completion_event = self.trace_service.record_event(
                run_id=request.run_id,
                phase=request.phase,
                agent_role=request.agent_role,
                event_type=TraceEventType.AGENT_COMPLETED,
                status=TraceStatus.SUCCEEDED,
                summary=f"{config.display_name} completed AgentScope task.",
                reasoning_summary=structured_output.reasoning_summary,
                output_payload=structured_output.model_dump(mode="json"),
                metadata={
                    "tool_call_count": len(bridge.executed_results),
                    "output_model": config.output_model.__name__,
                    "agentscope_agent": agent.name,
                },
            )
            return AgentRunResult(
                run_id=request.run_id,
                phase=request.phase,
                agent_role=request.agent_role,
                output_text=output_text,
                structured_output=structured_output,
                tool_results=list(bridge.executed_results),
                start_trace_event=start_event,
                completion_trace_event=completion_event,
            )
        except asyncio.TimeoutError as exc:
            timeout_message = (
                f"{config.display_name} AgentScope task timed out after "
                f"{config.execution.timeout_seconds} second(s)."
            )
            self.trace_service.record_event(
                run_id=request.run_id,
                phase=request.phase,
                agent_role=request.agent_role,
                event_type=TraceEventType.ERROR,
                status=TraceStatus.FAILED,
                summary=f"{config.display_name} timed out during AgentScope task.",
                error=timeout_message,
                metadata={
                    "exception_type": "TimeoutError",
                    "agentscope": True,
                    "timeout_seconds": config.execution.timeout_seconds,
                },
            )
            self.session.flush()
            raise AgentScopeExecutionError(timeout_message) from exc
        except Exception as exc:
            error_message = str(exc) or f"{type(exc).__name__} raised during AgentScope task."
            error_event = self.trace_service.record_event(
                run_id=request.run_id,
                phase=request.phase,
                agent_role=request.agent_role,
                event_type=TraceEventType.ERROR,
                status=TraceStatus.FAILED,
                summary=f"{config.display_name} failed AgentScope task.",
                error=error_message,
                metadata={
                    "exception_type": type(exc).__name__,
                    "agentscope": True,
                },
            )
            self.session.flush()
            if isinstance(exc, ValidationError):
                raise
            if isinstance(exc, AgentScopeExecutionError):
                raise
            raise AgentScopeExecutionError(error_message) from exc

    def _create_agent(
        self,
        config: AgentRoleConfig,
        bridge: AgentScopeToolBridge,
    ) -> Agent:
        return Agent(
            name=config.role.value,
            system_prompt=config.system_prompt,
            model=self.model_factory(config),
            toolkit=bridge.create_toolkit(config.allowed_tool_names),
            react_config=ReActConfig(max_iters=config.execution.max_iters),
        )

    @staticmethod
    def _build_user_message(request: AgentRunRequest, config: AgentRoleConfig) -> Msg:
        payload = {
            "task": request.task,
            "context": request.context,
            "available_tools": config.allowed_tool_names,
            "required_output_schema": config.output_model.model_json_schema(),
            "output_rule": (
                "Return the final answer as a single JSON object matching "
                "required_output_schema. Put reasoning only in reasoning_summary, "
                "as a concise summary, never as hidden chain-of-thought."
            ),
        }
        return UserMsg(
            name="connor_harness",
            content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )

    @staticmethod
    def _extract_text(response: Msg) -> str | None:
        text = response.get_text_content()
        return text if text else None

    @staticmethod
    def _extract_structured_payload(response: Msg, output_text: str | None) -> dict[str, Any]:
        if isinstance(response.metadata, dict):
            structured_output = response.metadata.get("structured_output")
            if isinstance(structured_output, dict):
                return structured_output

        if output_text is None:
            raise AgentScopeExecutionError("AgentScope response did not contain text output.")

        return AgentRunner._parse_json_object(output_text)

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any]:
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            stripped = "\n".join(lines).strip()

        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            start = stripped.find("{")
            end = stripped.rfind("}")
            if start < 0 or end < start:
                raise AgentScopeExecutionError(
                    "AgentScope response did not contain a JSON object."
                ) from None
            payload = json.loads(stripped[start : end + 1])

        if not isinstance(payload, dict):
            raise AgentScopeExecutionError("AgentScope response JSON must be an object.")
        return payload
