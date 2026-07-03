# ADR 0008: Loop Harness Control Boundary

Date: 2026-07-03

Status: Accepted

## Context

Connor.ai uses AgentScope 2.0 for agent execution, tool calls, event stream, middleware, and future team/worker organization.

Connor.ai still needs a product harness that decides:

- What phase a run is in.
- How many loop rounds are allowed.
- Whether to collect more, recluster, follow up, write, revise, reopen collection, finalize, pause, or fail.
- Which artifacts and trace records make the run replayable.

These decisions should not live only in prompts.

## Decision

Implement a Connor-owned loop harness that controls run state, quality gates, artifacts, and trace, while delegating agent execution to AgentScope through `AgentRunner`.

The boundary is:

```text
AgentScope:
  agent execution
  tool-call mechanics
  Agent / Toolkit / FunctionTool
  middleware and event stream later

Connor Harness:
  RunState lifecycle
  collect loop boundary
  writing loop boundary
  quality gate decisions
  budget enforcement
  artifact snapshots
  trace persistence
  finalization
```

## Consequences

Benefits:

- Run control is deterministic and testable.
- Infinite loops are bounded by `RunBudgets` and `HarnessConfig`.
- Gate decisions are structured and auditable.
- Agent output remains flexible, but harness decisions are persisted.
- Future scouts/evaluators/writers can be added without rewriting loop control.

Costs:

- Phase 6 introduces harness-level test doubles for writing side effects until real writer/reviewer agents persist reports themselves.
- Some quality checks are intentionally coarse until later phases implement richer evaluator and reviewer behavior.
- AgentScope event-stream tracing is still future work; Phase 6 traces harness decisions and AgentRunner outcomes.

## Validation

Phase 6 validates:

- Daily run creation.
- Collect loop selected-item gate.
- Collect loop budget exhaustion.
- Writing revision loop.
- Final report finalization.
- Trace and artifact creation for gate decisions and final report snapshots.

Checks:

- `python -m pytest tests\harness -q`: 7 passed.
- `python -m pytest -q`: 45 passed.
- `python -m compileall app tests`: passed.
