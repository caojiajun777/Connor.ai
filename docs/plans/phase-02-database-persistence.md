# Phase 2 Plan: Database Persistence

Status: Complete

Completed: 2026-07-03

## Goal

Persist the Phase 1 domain contract in a reliable database layer without coupling domain schemas to ORM implementation details.

Phase 2 answers:

```text
How do Connor.ai objects get stored, queried, restored, and reconstructed?
```

## Delivered Architecture

The persistence layer uses:

- SQLAlchemy 2.0 ORM for database table models.
- Alembic for migrations.
- Pydantic domain schemas as the source-of-truth business contracts.
- Repository classes as the only translation layer between domain objects and ORM records.

The package layout is:

```text
app/db/
  base.py
  session.py
  types.py
  models/

app/repositories/
  base.py
  domain.py
  runs.py

alembic/
  env.py
  versions/0001_initial_persistence_schema.py
```

## Tables Delivered

- `runs`
- `evidence_items`
- `candidate_items`
- `event_clusters`
- `evaluation_results`
- `watchlist_items`
- `archived_signals`
- `intelligence_threads`
- `daily_reports`
- `trace_events`
- `artifacts`
- `tool_calls`
- `model_calls`
- `review_results`
- `review_issues`

## Persistence Pattern

Each persisted domain object stores:

- High-frequency query columns, such as `run_id`, `status`, `phase`, `category`, `decision`, `source_type`, `created_at`.
- A complete `payload` column containing the full Phase 1 domain object JSON.

This gives the system two properties at once:

```text
Queryable tables for operations and dashboards.
Lossless restoration of domain objects for replay and audit.
```

`payload` uses PostgreSQL JSONB in production and SQLite JSON during local tests.

## Repository Layer

Repositories expose domain objects, not ORM records.

Examples:

- `RunRepository`
- `EvidenceRepository`
- `CandidateRepository`
- `EventClusterRepository`
- `EvaluationRepository`
- `WatchlistRepository`
- `ArchivedSignalRepository`
- `IntelligenceThreadRepository`
- `DailyReportRepository`
- `TraceEventRepository`
- `ArtifactRepository`
- `ToolCallRepository`
- `ModelCallRepository`
- `ReviewResultRepository`
- `ReviewIssueRepository`

The key reconstruction method is:

```python
RunRepository.get_full_state(run_id)
```

It restores:

- Run state.
- Evidence.
- Candidates.
- Clusters.
- Evaluations.
- Watchlist items.
- Archived signals.
- Intelligence threads.
- Reports.
- Trace events.
- Tool calls.
- Model calls.
- Artifacts.
- Review results and issues.

## Tests Delivered

Test files:

- `tests/db/test_schema_and_migrations.py`
- `tests/repositories/test_repository_persistence.py`

Coverage:

- ORM metadata contains all Phase 2 tables.
- Alembic upgrade creates all Phase 2 tables from an empty SQLite database.
- Core domain objects round-trip through repositories.
- Full run state can be reconstructed.
- Evidence -> candidate -> cluster -> evaluation lineage survives persistence.
- Daily report evidence map survives persistence.
- Watchlist, archive, and intelligence thread records survive persistence.
- Trace events are returned in timeline order.
- Tool calls, model calls, artifacts, review results, and review issues persist and restore.

## Checks Run

- `python -m pytest`: 20 passed.
- `python -m compileall app tests`: passed.

## Non-Goals Preserved

- No AgentScope integration.
- No real source tools.
- No loop harness runtime.
- No production tracing service.
- No FastAPI endpoints.

## Follow-up Phase

Phase 3 should build the tracing and artifact service layer on top of these repositories.

