# Phase 4 Plan: Tool Contract and Registry

Status: Complete

Completed: 2026-07-03

## Goal

Build the standard tool layer that future agents and source adapters will use.

Phase 4 answers:

```text
How does Connor.ai register tools?
How does an agent know which tools it may use?
How does a tool result become evidence?
How are tool calls traced and archived?
```

## Delivered Architecture

Added:

```text
app/tools/
  base.py
  registry.py
  executor.py
  builtin.py
```

The execution path is:

```text
Agent / Harness
-> ToolExecutor
-> ToolRegistry
-> ToolFunction
-> ToolEnvelope
-> ToolCallRecord + artifacts + TraceEvent
-> EvidenceItem records
-> Evidence-created TraceEvent
```

## Tool Contracts

Core objects:

- `ToolSpec`: static tool metadata and role policy.
- `ToolExecutionContext`: run, phase, agent role, query, params.
- `RegisteredTool`: spec plus callable.
- `ToolExecutionResult`: envelope, evidence, tool call, trace event, optional evidence trace.

Every tool must return a `ToolEnvelope` or a dictionary that validates into `ToolEnvelope`.

The executor verifies:

- Tool is registered.
- Agent role is allowed.
- Envelope `tool_name` matches the registered tool.
- Envelope `source_type` matches the registered tool.
- Result items normalize into `EvidenceItem` objects.

## Registry

`ToolRegistry` supports:

- `register`
- `require`
- `require_allowed`
- `list_tools`
- `list_for_agent`

Permissions are role-based through `ToolSpec.allowed_agent_roles`.

## Executor

`ToolExecutor` owns:

- Tool invocation.
- Envelope validation.
- Tool-call record creation.
- Request/response artifact storage.
- Error conversion into failed tool-call records.
- Evidence normalization and persistence.
- Evidence-created trace events.
- Stable evidence ID generation.

Tool failures do not crash the run by default. They return a failed envelope with normalized `ToolError`, a failed `ToolCallRecord`, and a failed trace event.

## Built-in Tools

Phase 4 includes two deterministic tools:

- `manual_seed`: inject curated/manual evidence into a run.
- `mock_search`: deterministic mock search for harness and agent development.

Real external source adapters are deliberately deferred until the tool contract is stable.

## Tests Delivered

Test files:

- `tests/tools/test_registry.py`
- `tests/tools/test_executor.py`

Coverage:

- Tool registration.
- Duplicate registration rejection.
- Role-based permission enforcement.
- Manual seed tool execution.
- Evidence persistence.
- Tool call trace linkage.
- Request/response artifact creation.
- Stable evidence IDs for the same input.
- Tool exception handling.
- Invalid envelope handling.

## Checks Run

- `python -m pytest`: 34 passed.
- `python -m compileall app tests`: passed.

## Non-Goals Preserved

- No AgentScope integration yet.
- No real external source adapters yet.
- No loop harness yet.
- No FastAPI endpoints.

## Follow-up Phase

Phase 5 should integrate AgentScope while keeping tool execution, tracing, and evidence persistence behind the service APIs created in Phases 3 and 4.

