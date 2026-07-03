# ADR 0004: SQLAlchemy Persistence with Domain Payloads

Date: 2026-07-03

Status: Accepted

## Context

Phase 1 established Pydantic domain schemas as Connor.ai's business contracts. Phase 2 needed to persist those contracts without turning ORM models into the source of truth.

Two options were considered:

- Use SQLModel and merge domain/API/database models.
- Use SQLAlchemy ORM separately and translate through repositories.

Connor.ai is expected to evolve across agents, tools, dashboards, migrations, and query needs. The database schema will likely need indexes, denormalized query columns, and JSONB boundaries that should not leak into agent output contracts.

## Decision

Use SQLAlchemy 2.0 ORM for persistence and keep Pydantic domain schemas independent.

Each persisted object stores:

- Explicit query columns for common access patterns.
- Full domain JSON in a `payload` column for lossless restoration.

Use PostgreSQL JSONB for production and SQLite JSON for local tests.

Business code should use repositories instead of ORM records directly.

## Consequences

Benefits:

- Domain contracts remain clean and framework-independent.
- Database schema can optimize for queries without changing agent contracts.
- Full domain objects can be restored for replay, audit, and dashboard rendering.
- Migration design can evolve without replacing Pydantic schemas.

Costs:

- Repository mapping code must be maintained.
- Some data is duplicated between query columns and `payload`.
- Future schema-version migrations need to update both query columns and payload shapes carefully.

## Validation

Phase 2 delivered:

- ORM models for all persisted Phase 1 objects.
- Alembic migration for the complete persistence schema.
- Repository round-trip tests.
- Full run-state reconstruction tests.

