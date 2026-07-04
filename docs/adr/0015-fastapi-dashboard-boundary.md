# ADR 0015: FastAPI Dashboard Boundary

Date: 2026-07-04

Status: Accepted

## Context

Connor.ai now has persisted domain objects for runs, evidence, candidates, clusters, evaluations, watchlist memory, reports, reviews, artifacts, and trace.

The next layer is a dashboard API. The API must serve the frontend without taking ownership of agent orchestration, domain mutation rules, or trace construction.

## Decision

Introduce a dedicated FastAPI layer under `app/api`.

Responsibilities:

- request/response schemas for dashboard contracts
- HTTP routing
- database session dependency injection
- 404/409 behavior
- JSON serialization of domain objects

Non-responsibilities:

- direct agent execution
- custom persistence rules outside repositories/services
- hidden reasoning or chain-of-thought exposure
- frontend-specific presentation logic beyond stable dashboard payloads

`POST /runs/daily` may create a scheduled run through `DailyRunHarness.create_run`, but it does not execute collect or writing loops.

## Consequences

Positive:

- Dashboard can read stable run/report/trace/watchlist/thread structures.
- API contract remains thin and testable.
- The harness remains the only owner of loop execution.
- Persistence stays behind repositories and services.
- TestClient coverage validates real HTTP behavior without requiring a running server.

Trade-offs:

- The first API contract returns full run state in one response; pagination is deferred.
- Authentication is not implemented yet.
- `POST /runs/daily` creates scheduled runs only; execution endpoints can be added after worker/queue design is settled.

## Rejected Alternatives

Expose ORM rows directly.

- Rejected because payload serialization and dashboard contract stability should not depend on SQLAlchemy internals.

Let API endpoints execute full daily runs synchronously.

- Rejected because source collection and AgentScope execution will need queue/runtime boundaries.

Build Next.js first and shape the API reactively.

- Rejected because Connor.ai's data contract should be stable before frontend work starts.
