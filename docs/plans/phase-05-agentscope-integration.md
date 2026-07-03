# Phase 5 Plan: AgentScope Integration

Status: Complete

Completed: 2026-07-03

Corrected: 2026-07-03

## Goal

Make AgentScope 2.0 the first-choice and first-class agent execution layer for Connor.ai.

Phase 5 answers:

```text
How does Connor.ai create AgentScope agents?
How are Connor tools exposed through AgentScope Toolkit?
How do AgentScope tool calls still produce Connor evidence and trace?
How is final structured output validated after AgentScope finishes?
```

## Final Architecture

Delivered:

```text
app/agents/
  config.py
  outputs.py
  prompts.py
  registry.py
  schemas.py
  agentscope_tools.py
  runner.py
```

Removed from the final design:

```text
app/agents/runtime.py
app/agents/deterministic.py
app/agents/agentscope_adapter.py
```

The execution path is now:

```text
Connor Harness / Test
-> AgentRunner
-> AgentScope Agent
-> AgentScope Toolkit
-> Connor FunctionTool bridge
-> ToolExecutor
-> TraceService / EvidenceRepository / ArtifactService
-> AgentScope Agent final message
-> Connor structured output validation
-> Agent completion trace
```

## Dependency Decision

AgentScope is a main dependency, not an optional extra:

```text
agentscope>=2.0
```

Rationale:

- Connor.ai is designed around AgentScope 2.0.
- Agent, tool call, middleware, event stream, and team/worker organization should be native AgentScope concepts.
- Connor should not define its own replaceable agent runtime contract.

## Agent Contracts

Core objects:

- `AgentRoleConfig`: role, prompt, allowed tools, output schema, execution config.
- `AgentExecutionConfig`: AgentScope execution limits and model hints.
- `AgentRunRequest`: run, phase, role, task, context.
- `AgentRunResult`: text output, structured output, Connor tool results, trace events.
- `AgentScopeExecutionError`: runner-level failure when AgentScope cannot produce a valid Connor result.

Structured outputs:

- `AgentStructuredOutput`
- `ScoutOutput`
- `EvaluatorOutput`
- `WriterOutput`
- `ReviewerOutput`
- `EditorOutput`

These schemas are Connor business contracts, not a custom agent runtime.

## AgentScope Runner

`AgentRunner` now directly creates:

```text
agentscope.agent.Agent(
  name=role.value,
  system_prompt=role prompt,
  model=model_factory(config),
  toolkit=AgentScope Toolkit,
  react_config=ReActConfig(max_iters=config.execution.max_iters)
)
```

The runner owns:

- Agent start trace.
- AgentScope `UserMsg` construction.
- AgentScope `Agent.reply(...)` invocation.
- Final JSON extraction.
- Pydantic structured-output validation.
- Agent completion/error trace.

The runner does not own:

- A custom ReAct loop.
- A custom tool-call protocol.
- A replaceable agent runtime abstraction.

## Tool Bridge

`AgentScopeToolBridge` converts Connor tools into AgentScope tools:

```text
ToolRegistry.list_for_agent(role)
-> ConnorFunctionTool(FunctionTool)
-> Toolkit(tools=[...])
```

Each AgentScope tool call receives:

```json
{
  "query": "...",
  "params": {}
}
```

Each tool returns agent-visible JSON containing:

```json
{
  "tool_name": "...",
  "status": "...",
  "query": "...",
  "tool_call_id": "...",
  "trace_event_id": "...",
  "evidence_ids": [],
  "items": [],
  "errors": [],
  "raw_artifact_ref": {},
  "metadata": {}
}
```

The real side effects still happen through Connor's Phase 4 boundary:

- `ToolExecutor`
- `ToolCallRecord`
- `EvidenceItem`
- `TraceEvent`
- `Artifact`

## Permission Model

AgentScope receives only role-allowed tools.

Connor's policy remains the source of truth:

```text
ToolRegistry.require_allowed(tool_name, agent_role)
```

`ConnorFunctionTool` returns an AgentScope allow decision because the background worker has already scoped tools by role. A model cannot execute a Connor tool unless it is present in the role-specific Toolkit and passes `ToolExecutor`.

## Tests Delivered

Test files:

- `tests/agents/test_registry.py`
- `tests/agents/test_runner.py`

Coverage:

- Default role registry output models.
- Role-specific tool binding.
- AgentScope `Agent.reply(...)` execution.
- AgentScope model response with `ToolCallBlock`.
- AgentScope `Toolkit` executing Connor `FunctionTool`.
- Tool execution through `ToolExecutor`.
- Evidence persistence from AgentScope tool calls.
- Agent start/completion/error traces.
- Structured output validation after final AgentScope message.
- Role-scoped Toolkit excludes forbidden tools.

## Checks Run

- `python -m pytest tests\agents -q`: 4 passed.
- `python -m compileall app tests`: passed.
- `python -m pytest -q`: 38 passed.

## Non-Goals Preserved

- No collect loop harness yet.
- No real model provider configuration yet.
- No real external source adapters yet.
- No FastAPI endpoints.
- No AgentScope team/worker topology beyond single-agent runner yet.

## Follow-up Phase

Phase 6 should implement the Connor loop harness on top of this AgentScope-first runner.

The harness should own:

- Run state.
- Loop boundaries.
- Quality gates.
- Artifact archiving.
- Trace persistence.

AgentScope should continue to own:

- Agent execution.
- Tool calls.
- Agent event stream.
- Middleware.
- Future team/worker organization.
