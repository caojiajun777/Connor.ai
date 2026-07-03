# Phase 9 Plan: Clusterer

Status: Complete

Completed: 2026-07-03

## Goal

Replace Phase 7/8's Scout-side bootstrap cluster creation with a real Clusterer path:

```text
Scouts
-> CandidateItem records
-> AgentScope Clusterer
-> ClusterDraft output
-> Connor ClusterOutputMaterializer
-> EventCluster records
-> temporary bootstrap EvaluationResult if Phase 10 evaluators are absent
```

The Clusterer does not write database records directly. It proposes event clusters through structured output, and Connor validates and persists them.

## Delivered Architecture

Added:

```text
app/clusterer/__init__.py
app/clusterer/materialization.py
app/clusterer/tasks.py
```

Updated:

```text
app/agents/outputs.py
app/agents/registry.py
app/agents/__init__.py
app/harness/collect.py
app/harness/config.py
```

## Agent Output Extension

Added:

- `ClusterTimelineDraft`
- `ClusterDraft`
- `ClustererOutput`

Clusterer now returns:

```json
{
  "summary": "...",
  "reasoning_summary": "...",
  "cluster_drafts": [
    {
      "category": "confirmed_event",
      "title": "...",
      "canonical_claim": "...",
      "candidate_ids": ["..."],
      "evidence_ids": ["..."],
      "timeline": [
        {
          "summary": "...",
          "candidate_ids": ["..."],
          "evidence_ids": ["..."]
        }
      ],
      "conflict_summary": "...",
      "dedupe_key": "..."
    }
  ]
}
```

`create_default_agent_role_registry` now binds `AgentRole.CLUSTERER` to `ClustererOutput`.

## Materialization Boundary

`ClusterOutputMaterializer` owns:

- candidate lookup and run ownership validation
- evidence lineage expansion from candidate evidence
- evidence existence validation
- deterministic cluster ids
- dedupe-key based merge
- canonical claim persistence
- timeline entry construction
- conflict summary preservation
- early-signal to official-confirmation metadata links
- cluster creation trace events
- run lineage updates

The materializer creates or merges `EventCluster` records.

## Dedupe and Merge

If a Clusterer draft provides a `dedupe_key`, Connor uses it directly.

If no key is provided, Connor derives a deterministic key from:

- category
- normalized entities
- normalized tickers
- normalized topics
- canonical claim slug

When an existing cluster with the same dedupe key exists for the run, the materializer merges:

- candidate ids
- evidence ids
- entities
- tickers
- topics
- timeline entries
- conflict summary
- metadata

## Confirmation Links

When a cluster contains both:

- `early_signal` candidates
- `confirmed_event` or `official_update` candidates

Connor records:

```json
{
  "confirmation_linked": true,
  "confirmed_prior_signal_candidate_ids": ["..."],
  "confirmation_candidate_ids": ["..."]
}
```

This is the first concrete bridge toward the later intelligence-thread logic chain.

## Temporary Evaluator Bridge

Phase 10 will implement the real Evaluator group.

Until then, when a Clusterer task exists but no Evaluator task exists, the collect loop can create a marked bootstrap evaluation:

```json
{
  "bootstrap_clusterer_evaluation": true
}
```

This preserves a runnable closed loop without pretending Phase 10 is complete.

## Harness Integration

`CollectLoopHarness` now:

- passes compact `candidate_context` into Clusterer tasks
- materializes Clusterer outputs during the clustering phase
- leaves Scout bootstrap behavior intact when no Clusterer task is scheduled
- uses Clusterer bootstrap evaluations only when no Evaluator task is scheduled

## Tests Delivered

Added:

```text
tests/clusterer/test_materialization.py
tests/harness/test_clusterer_closed_loop.py
```

Updated:

```text
tests/agents/test_registry.py
```

Coverage:

- Clusterer output schema binding.
- Cluster creation from early signal plus official confirmation.
- Evidence union from candidate lineage.
- Confirmation link metadata.
- Conflict metadata.
- Dedupe-key merge into an existing cluster.
- Missing candidate rejection.
- Full AgentScope path from Scout candidates to Clusterer cluster to collect gate.
- Trace events for candidate, cluster, evaluation, and gate.

## Checks Run

- `python -m pytest tests\clusterer tests\harness\test_clusterer_closed_loop.py tests\agents\test_registry.py -q`: 5 passed.
- `python -m pytest -q`: 56 passed.
- `python -m compileall app tests`: passed.

## Non-Goals Preserved

- No production Evaluator group yet.
- No Watchlist/Archive/Thread write path yet.
- No real external source adapters yet.
- No report writing changes in this phase.

## Follow-up Phase

Phase 10 should implement the Evaluator group:

- Frontier Evaluator
- Event Evaluator
- Market Evaluator
- structured evaluation drafts
- follow-up / watch / archive / select outcomes
- replacement of `bootstrap_clusterer_evaluation`
