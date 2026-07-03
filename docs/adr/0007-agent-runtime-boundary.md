# ADR 0007: AgentScope-First Agent Boundary

Date: 2026-07-03

Status: Accepted

Supersedes: the earlier Phase 5 draft that introduced a Connor-owned `AgentRuntime` protocol.

## Context

Connor.ai is intended to use AgentScope 2.0 for agent execution, tool calls, event stream, middleware, and agent team / worker organization.

Connor.ai also has product guarantees that must stay outside prompts:

- Stable domain schemas.
- Tool execution contracts.
- Evidence lineage.
- Trace persistence.
- Artifact storage.
- Loop boundaries.
- Quality gates.

The first Phase 5 implementation incorrectly introduced a Connor-owned runtime protocol with deterministic and optional AgentScope adapters. That made AgentScope secondary, even though AgentScope is the intended first-choice framework.

## Decision

AgentScope is a main dependency and the first-class agent execution layer.

Connor.ai will not define a replaceable agent runtime contract.

`AgentRunner` directly creates and invokes AgentScope:

```text
AgentScope Agent
-> AgentScope Toolkit
-> AgentScope FunctionTool
-> Connor ToolExecutor
-> Connor trace/evidence/artifact persistence
```

Connor-owned code remains responsible for:

- Role configs and system prompts.
- Structured output schemas.
- Tool registry policy.
- Tool execution side effects.
- Trace and artifact persistence.
- Run state and loop gates in later phases.

AgentScope remains responsible for:

- Agent execution.
- ReAct iteration.
- Tool-call blocks and tool result blocks.
- Toolkit mechanics.
- Middleware and event stream in later phases.
- Future team/worker organization.

## Consequences

Benefits:

- The implementation now matches the product architecture.
- AgentScope `Agent.reply(...)` is on the tested execution path.
- AgentScope `Toolkit` and `FunctionTool` are the actual tool-call mechanism.
- Connor keeps traceable product state without replacing AgentScope.
- Future middleware/event-stream work can attach to AgentScope directly.

Costs:

- Tests require AgentScope to be installed.
- Test determinism is provided by an AgentScope `ChatModelBase` test double, not by a Connor runtime.
- Any AgentScope API changes affect `app/agents/runner.py` and `app/agents/agentscope_tools.py`.

## Validation

Phase 5 now validates:

- AgentScope package is a main dependency.
- AgentScope `Agent` is directly invoked by `AgentRunner`.
- AgentScope `ToolCallBlock` triggers a Connor tool through `Toolkit`.
- Connor `ToolExecutor` persists evidence, tool calls, artifacts, and trace events.
- Final AgentScope text is parsed and validated against Connor structured output schemas.
- Role-specific Toolkit construction excludes forbidden tools.

Checks:

- `python -m pytest tests\agents -q`: 4 passed.
- `python -m compileall app tests`: passed.
- `python -m pytest -q`: 38 passed.
