# Phase 11 Plan: Watchlist, Archive, and Intelligence Threads

Status: Complete

Completed: 2026-07-04

## Goal

Turn evaluator decisions into cost-aware memory:

```text
EvaluationResult records
-> Watchlist Agent or deterministic lifecycle policy
-> WatchlistItem / ArchivedSignal / IntelligenceThread records
-> traceable memory state
```

The goal is not to keep every signal active forever. Active tracking must stay bounded by TTLs, while archived signals remain available for future logic-chain analysis.

## Delivered Architecture

Added:

```text
app/watchlist/__init__.py
app/watchlist/tasks.py
app/watchlist/materialization.py
app/watchlist/lifecycle.py
```

Updated:

```text
app/agents/outputs.py
app/agents/__init__.py
app/agents/registry.py
app/core/ids.py
app/harness/collect.py
app/harness/config.py
app/harness/gates.py
app/services/tracing.py
```

## Agent Output Extension

Added:

- `WatchlistDraft`
- `ArchiveDraft`
- `ThreadTimelineDraft`
- `ThreadDraft`
- `WatchlistAgentOutput`

Watchlist Agent can now return:

```json
{
  "summary": "...",
  "reasoning_summary": "...",
  "watchlist_drafts": [
    {
      "source_evaluation_id": "...",
      "cluster_ids": ["..."],
      "topic": "...",
      "thesis": "...",
      "watch_tier": "short",
      "priority": "high",
      "ttl_days": 7,
      "reactivation_rules": ["..."],
      "open_questions": ["..."]
    }
  ],
  "archive_drafts": [],
  "thread_drafts": []
}
```

`AgentRole.WATCHLIST_AGENT` is now bound to `WatchlistAgentOutput` in the default AgentScope role registry.

## Materialization Boundary

`WatchlistOutputMaterializer` owns:

- run phase and role validation
- evaluation, cluster, evidence, and watchlist lineage checks
- deterministic watch/archive/thread ids
- WatchlistItem create/update/reactivation
- ArchivedSignal create/update
- Watchlist status transition to `expired` or `archived`
- IntelligenceThread create/update and timeline merge
- run lineage updates for watchlist/archive/thread ids
- `WATCHLIST_UPDATED`, `ARCHIVE_CREATED`, and `THREAD_UPDATED` trace events

Watchlist Agent does not write database records directly.

## Deterministic Lifecycle

Added `WatchlistLifecycleService`.

It performs two automatic operations:

- `sync_evaluation_memory()`: when no Watchlist Agent task is scheduled, create default memory from evaluator decisions.
- `expire_due_items()`: archive active/reactivated watch items whose `watch_until` has passed.

Default policy:

- `select_early_signal`, `short_watch`, and `followup_later` can create watchlist items.
- `archive` can create archived signals.
- `select_confirmed` can create or update intelligence threads.
- Short watch TTL defaults to 7 days.
- Event watch TTL defaults to 14 days.
- Strategic watch TTL defaults to 45 days.

## Harness Integration

`CollectLoopHarness` now:

- runs watchlist expiration during the `watchlist_update` phase
- materializes `WatchlistAgentOutput` when Watchlist Agent tasks are scheduled
- injects compact `memory_context` into Watchlist Agent tasks
- falls back to deterministic evaluator-memory sync when no Watchlist Agent task is scheduled

Added harness config:

```python
materialize_watchlist_outputs: bool = True
expire_due_watchlist_items: bool = True
auto_materialize_watchlist_from_evaluations: bool = True
```

Collect-gate metrics now include:

- `watchlist_count`
- `archive_count`
- `thread_count`

## Tests Delivered

Added:

```text
tests/watchlist/test_materialization.py
tests/watchlist/test_lifecycle.py
tests/harness/test_watchlist_closed_loop.py
```

Updated:

```text
tests/agents/test_registry.py
```

Coverage:

- Watchlist Agent output schema binding.
- Watchlist draft materialization into WatchlistItem.
- Implicit IntelligenceThread creation for watch items.
- Archive draft materialization into ArchivedSignal.
- Watchlist status transition to archived.
- Due watch expiration into TTL archive.
- Deterministic evaluator-memory sync.
- Trace events for watchlist, archive, and thread updates.
- Full AgentScope Watchlist Agent closed loop.

## Checks Run

- `python -m pytest tests\watchlist tests\harness\test_watchlist_closed_loop.py tests\agents\test_registry.py -q`: 6 passed.
- `python -m pytest -q`: 76 passed.
- `python -m compileall app tests`: passed.

## Non-Goals Preserved

- No final report generation changes in this phase.
- No external source expansion.
- No dashboard API yet.
- No cross-run semantic retrieval beyond persisted intelligence threads.

## Follow-up Phase

Phase 12 should implement the Writer/Reviewer/Editor materialization path:

- generate `DailyReport.full_markdown`
- generate `DailyReport.full_json`
- generate `evidence_map`
- include watchlist updates and trace timeline ids
- enforce reviewer checks that prevent early signals from being written as facts
