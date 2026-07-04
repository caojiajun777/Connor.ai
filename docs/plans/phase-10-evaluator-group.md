# Phase 10 Plan: Evaluator Group

Status: Complete

Completed: 2026-07-04

## Goal

Replace the temporary `bootstrap_clusterer_evaluation` bridge with real AgentScope evaluator roles:

```text
EventCluster records
-> AgentScope Evaluator agents
-> EvaluationDraft output
-> Connor EvaluatorOutputMaterializer
-> EvaluationResult records
-> Collect quality gate
```

The Evaluator agents do not write database records directly. They propose structured evaluation drafts, and Connor validates, persists, traces, and gates those drafts.

## Delivered Architecture

Added:

```text
app/evaluators/__init__.py
app/evaluators/profiles.py
app/evaluators/tasks.py
app/evaluators/materialization.py
```

Updated:

```text
app/agents/outputs.py
app/agents/__init__.py
app/agents/registry.py
app/harness/collect.py
app/harness/config.py
```

## Agent Output Extension

Added `EvaluationDraft` and extended `EvaluatorOutput`.

Evaluator agents now return:

```json
{
  "summary": "...",
  "reasoning_summary": "...",
  "evaluation_drafts": [
    {
      "cluster_id": "...",
      "evaluator_type": "frontier",
      "dimension_scores": {
        "information_gap": 8,
        "specificity": 7,
        "source_proximity": 4,
        "potential_impact": 8,
        "trackability": 9
      },
      "total_score": 7.2,
      "decision": "select_early_signal",
      "reasoning_summary": "...",
      "risk_flags": [],
      "required_followups": ["..."],
      "missing_evidence": ["..."]
    }
  ]
}
```

`create_default_agent_role_registry` still binds all evaluator roles to `EvaluatorOutput`, but their system prompts now also include role-specific evaluator profiles.

## Evaluator Profiles

Added three profiles:

- Frontier Evaluator: early signals, code/model anomalies, research signals, and other frontier material.
- Event Evaluator: confirmed events and official updates.
- Market Evaluator: tech-finance items.

Frontier Evaluator is intentionally permissive for unconfirmed but useful signals. It can select an early signal when the item is specific, information-rich, potentially impactful, and trackable. It must preserve missing evidence and follow-up points.

Event Evaluator is stricter. `select_confirmed` requires no missing evidence and a total score of at least 6.

Market Evaluator requires AI relevance, market impact, supply-chain impact, and ticker relevance. Select/follow-up decisions require a ticker path or explicit ticker metadata.

## Materialization Boundary

`EvaluatorOutputMaterializer` owns:

- evaluator role validation
- run phase validation
- cluster lookup and run ownership validation
- profile-level draft validation
- deterministic evaluation id generation
- `EvaluationResult` persistence
- selected cluster marking for select decisions
- `EVALUATION_CREATED` trace events
- run metadata updates for evaluator materialization replay

Invalid evaluator output raises `HarnessError` before it becomes persisted intelligence state.

## Harness Integration

`CollectLoopHarness` now:

- passes compact `cluster_context` into Evaluator tasks
- materializes `EvaluatorOutput.evaluation_drafts` during the evaluating phase
- keeps Phase 9 clusterer bootstrap behavior only when no evaluator task is scheduled
- lets `QualityGateService` route selected, follow-up, recluster, manual-review, and failure outcomes from real `EvaluationResult` records

Added harness config:

```python
materialize_evaluator_outputs: bool = True
```

## Tests Delivered

Added:

```text
tests/evaluators/test_profiles.py
tests/evaluators/test_materialization.py
tests/harness/test_evaluator_closed_loop.py
```

Updated:

```text
tests/agents/test_registry.py
```

Coverage:

- Default evaluator profile registry coverage.
- Evaluator task profile/context construction.
- Frontier Evaluator accepting trackable unconfirmed early signals.
- Event Evaluator rejecting early-signal clusters.
- Market Evaluator requiring required score dimensions and ticker path.
- Evaluator materialization into `EvaluationResult` records.
- Trace creation for evaluator decisions.
- Selected cluster marking.
- Invalid evaluator draft rejection.
- Full AgentScope Frontier Evaluator closed loop from persisted cluster to evaluation to collect gate.
- Registry prompt inclusion of evaluator profile constraints.

## Checks Run

- `python -m pytest tests\evaluators tests\harness\test_evaluator_closed_loop.py tests\agents\test_registry.py -q`: 10 passed.
- `python -m pytest -q`: 71 passed.
- `python -m compileall app tests`: passed.

## Non-Goals Preserved

- No Watchlist/Archive/Thread write path yet.
- No report writer/reviewer/editor materialization changes in this phase.
- No real external source adapters yet.
- No AgentScope team/worker topology beyond single-role task execution yet.

## Follow-up Phase

Phase 11 should implement cost-aware memory:

- Watchlist item creation from evaluator decisions.
- TTL-based expiration.
- Archive records for stale, superseded, disproven, or low-value signals.
- Intelligence Threads that connect early signals, confirmations, archives, and later outcomes into historical logic chains.
