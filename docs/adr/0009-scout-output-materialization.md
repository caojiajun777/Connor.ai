# ADR 0009: Scout Output Materialization Boundary

Date: 2026-07-03

Status: Accepted

## Context

Phase 5 made AgentScope the first-class agent runtime.

Phase 6 added the Connor loop harness.

Phase 7 needs one Scout to close the loop from:

```text
AgentScope tool call
-> EvidenceItem
-> Scout structured output
-> CandidateItem
-> collect gate
```

The system must not let agents directly write arbitrary database records. Agent outputs must land in Connor domain structures through a controlled boundary.

## Decision

Add `CandidateDraft` to `ScoutOutput`.

Add `ScoutOutputMaterializer` as the Connor-owned boundary that converts validated Scout output into persisted domain objects.

The materializer owns:

- evidence id resolution
- `CandidateItem` creation
- candidate creation trace
- run lineage updates
- optional single-agent bootstrap cluster/evaluation

The AgentScope agent owns:

- exploration
- tool calls
- final structured Scout output

## Single-Agent Bootstrap

To prove the Phase 7 closed loop before the full Clusterer and Evaluator phases exist, the materializer can create provisional:

- `EventCluster`
- `EvaluationResult`

These records include:

```json
{
  "bootstrap_single_agent": true
}
```

Bootstrap runs only when no explicit Clusterer or Evaluator tasks are scheduled.

## Consequences

Benefits:

- Agents cannot bypass Connor validation and persistence.
- Phase 7 proves real AgentScope tool output can become domain state.
- The collect gate can advance without waiting for future full Clusterer/Evaluator implementations.
- Later phases can disable or bypass bootstrap by scheduling real Clusterer/Evaluator tasks.

Costs:

- Bootstrap cluster/evaluation logic is deliberately simple.
- Later production Clusterer/Evaluator behavior must replace bootstrap records for full multi-agent runs.
- Materialization is now a first-class boundary that must evolve with agent output schemas.

## Validation

Phase 7 validates:

- AgentScope `ToolCallBlock` executes `manual_seed`.
- Evidence is persisted by `ToolExecutor`.
- Scout final output includes `candidate_drafts`.
- Candidate, cluster, evaluation, and gate trace events are recorded.
- Collect gate enters writing from the single-agent generated item.

Checks:

- `python -m pytest tests\harness -q`: 8 passed.
- `python -m pytest -q`: 46 passed.
- `python -m compileall app tests`: passed.
