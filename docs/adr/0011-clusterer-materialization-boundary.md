# ADR 0011: Clusterer Materialization Boundary

Date: 2026-07-03

Status: Accepted

## Context

Phase 7 and Phase 8 used a marked bootstrap path where Scout materialization could create provisional clusters and evaluations when no real Clusterer or Evaluator tasks were scheduled.

Phase 9 needs production clustering behavior without giving agents direct database write access.

The Clusterer must be able to:

- deduplicate related candidates
- create canonical claims
- preserve evidence lineage
- preserve conflicting evidence
- link early signals to later official confirmations

## Decision

Add Clusterer-specific structured output:

- `ClusterTimelineDraft`
- `ClusterDraft`
- `ClustererOutput`

Bind `AgentRole.CLUSTERER` to `ClustererOutput`.

Add `ClusterOutputMaterializer` as the Connor-owned boundary that converts Clusterer drafts into persisted `EventCluster` records.

## Boundary

AgentScope Clusterer owns:

- reading candidate context
- deciding which candidates belong together
- proposing title, canonical claim, category, timeline, conflict summary, and dedupe key

Connor harness owns:

- candidate lookup
- run ownership validation
- evidence existence validation
- evidence lineage expansion
- deterministic ids
- dedupe-key merge behavior
- event cluster persistence
- trace events
- run lineage updates
- temporary evaluator bootstrap until Phase 10

## Confirmation Links

When a materialized cluster contains both early-signal candidates and official/confirmed candidates, Connor records structured metadata:

```json
{
  "confirmation_linked": true,
  "confirmed_prior_signal_candidate_ids": ["..."],
  "confirmation_candidate_ids": ["..."]
}
```

This makes the historical logic chain explicit and queryable later by Watchlist and Intelligence Threads.

## Temporary Evaluator Bridge

Phase 10 will replace evaluator bootstrap.

Until then, Clusterer materialization may create a marked `EvaluationResult` when no evaluator task is scheduled:

```json
{
  "bootstrap_clusterer_evaluation": true
}
```

This keeps the collect loop runnable while preserving the architecture boundary.

## Import Boundary

`app.clusterer` avoids importing harness modules at package-import time.

Reason:

- `CollectLoopHarness` imports clusterer materialization.
- Tests may import clusterer materialization independently.
- Eager cross-imports would create circular dependencies.

Clusterer modules therefore use lazy imports for harness-only types.

## Consequences

Benefits:

- Clusterer is now a real AgentScope role with a role-specific output schema.
- Agents still cannot write arbitrary clusters directly.
- Dedupe and merge behavior is deterministic and testable.
- Conflicts and confirmation links are preserved in structured cluster metadata.
- The Phase 9 path can run end-to-end before Phase 10 evaluators exist.

Costs:

- Bootstrap evaluation still exists until Phase 10.
- Dedupe-key quality depends on either agent-provided keys or the deterministic fallback.
- Later semantic clustering may need embeddings or stronger similarity logic, but the persistence boundary can remain the same.

## Validation

Phase 9 validates:

- Clusterer output schema binding in the agent registry.
- Cluster creation from multiple candidates.
- Dedupe-key merge behavior.
- Conflict metadata preservation.
- Early-signal to official-confirmation linking.
- Full AgentScope Scout-to-Clusterer closed loop.

Checks:

- `python -m pytest tests\clusterer tests\harness\test_clusterer_closed_loop.py tests\agents\test_registry.py -q`: 5 passed.
- `python -m pytest -q`: 56 passed.
- `python -m compileall app tests`: passed.
