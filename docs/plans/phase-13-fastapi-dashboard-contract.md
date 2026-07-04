# Phase 13 Plan: FastAPI and Dashboard Contract

Status: Complete

Completed: 2026-07-04

## Goal

Expose Connor.ai's persisted run, report, memory, and trace state through a stable API contract for the future Next.js Dashboard.

The API layer should not run agents by itself except for creating scheduled run records. It should provide replayable, dashboard-ready read surfaces over the domain/repository layer.

## Delivered Architecture

Added:

```text
app/api/__init__.py
app/api/dependencies.py
app/api/main.py
app/api/routes.py
app/api/schemas.py
app/main.py
tests/api/__init__.py
tests/api/test_routes.py
```

Updated:

```text
pyproject.toml
app/repositories/base.py
app/repositories/domain.py
docs/PROGRESS.md
docs/DEV_LOG.md
docs/plans/phase-13-fastapi-dashboard-contract.md
docs/adr/0015-fastapi-dashboard-boundary.md
```

## Endpoints

Implemented:

- `POST /runs/daily`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/trace`
- `GET /runs/{run_id}/clusters`
- `GET /reports/{report_id}`
- `GET /watchlist`
- `GET /threads`
- `GET /threads/{thread_id}`

## API Contract

The public response layer uses explicit schemas:

- `RunDetailResponse`
- `TraceTimelineResponse`
- `ClusterListResponse`
- `ReportResponse`
- `WatchlistListResponse`
- `ThreadListResponse`
- `ThreadResponse`

These schemas expose domain payloads in dashboard-ready envelopes without adding any hidden reasoning fields.

## Behavior

`POST /runs/daily`:

- creates a scheduled run
- records initial run trace
- commits the transaction
- returns the same full run detail shape as `GET /runs/{run_id}`
- returns `409` when an explicit `run_id` already exists

Read endpoints:

- return `404` for missing runs, reports, or threads
- read through repositories/services rather than raw ORM access
- serialize Pydantic domain objects with `model_dump(mode="json")`
- provide stable structures for report markdown, dashboard JSON, evidence maps, watchlist updates, and trace timelines

## Tests

Added API tests for:

- daily run creation
- duplicate run conflict
- run detail response
- trace response
- cluster list response
- report response
- watchlist response with status filter
- thread list and detail responses
- 404 behavior

API tests use a thread-safe SQLite `StaticPool` setup because FastAPI `TestClient` runs requests in a worker thread.

## Checks

- `python -m pytest tests\api\test_routes.py -q`: 3 passed.
- `python -m pytest -q`: 91 passed.
- `python -m compileall app tests`: passed.
- `git diff --check`: passed.

## Effect

Connor.ai now has the backend API surface needed by the future dashboard without changing the core harness:

```text
Database / Repositories / Services
-> FastAPI routes
-> Dashboard response schemas
-> Next.js Dashboard later
```

## Open Follow-ups

- Add authentication and operator permissions before exposing this beyond local development.
- Add pagination/filtering once real source volume grows.
- Add a Dashboard frontend in the later Next.js phase.
- Phase 14 can begin real source expansion now that core write/read surfaces are stable.
