# Connor.ai Progress Tracker

Last updated: 2026-07-03

## Current Status

Project state: Phase 5 complete. Connor.ai now has domain contracts, persistence, tracing/artifacts, tools, and a tested AgentScope-first agent execution path.

Next phase: Phase 6, Loop Harness.

## Phase Progress

| Phase | Name | Status | Notes |
|---|---|---|---|
| 1 | Domain Schemas | Complete | Full Pydantic domain contract, fixtures, validation tests, and ADRs delivered. |
| 2 | Database Persistence | Complete | SQLAlchemy ORM, Alembic migration, repositories, and persistence tests delivered. |
| 3 | Tracing and Artifacts | Complete | ArtifactService, TraceService, timeline reconstruction, and service tests delivered. |
| 4 | Tool Contract and Registry | Complete | ToolSpec, ToolRegistry, ToolExecutor, manual seed/mock tools, evidence normalization, and tool tests delivered. |
| 5 | AgentScope Integration | Complete | AgentScope is a main dependency; AgentRunner uses AgentScope Agent/Toolkit/FunctionTool directly. |
| 6 | Loop Harness | Not started | Collect and writing state machines. |
| 7 | Single-Agent Closed Loop | Not started | First end-to-end agent path. |
| 8 | All Scouts | Not started | Five scout roles. |
| 9 | Clusterer | Not started | Candidate dedupe and canonical claims. |
| 10 | Evaluator Group | Not started | Frontier, Event, Market evaluators. |
| 11 | Watchlist + Archive + Intelligence Threads | Not started | Cost-aware memory and logic chains. |
| 12 | Writing Loop | Not started | Writer, Reviewer, Editor loop. |
| 13 | FastAPI and Dashboard Contract | Not started | External API contract. |
| 14 | Source Expansion | Not started | Real source breadth after core reliability. |

## Phase 1 Results

Delivered:

- Python project skeleton for domain contracts.
- Complete enum layer for phases, roles, sources, decisions, watch states, trace states, calls, review, and reports.
- Complete Pydantic schemas for run state, evidence, candidates, clusters, evaluations, watchlist, archive, intelligence threads, reports, trace events, artifacts, tool calls, model calls, tool envelopes, and reviews.
- Representative fixtures for Early Signal, Confirmed Event, and Tech-Finance examples.
- Validation tests for serialization, enum JSON compatibility, lineage, early-signal rules, confirmed-event evidence strength, watch TTL, archive lineage, intelligence threads, report consistency, tool normalization, and trace redaction boundaries.

Checks:

- `python -m pytest`: 16 passed.
- `python -m compileall app tests`: passed.

## Phase 2 Results

Delivered:

- SQLAlchemy 2.0 database foundation with declarative metadata and session helpers.
- ORM table models for all Phase 1 persisted objects.
- PostgreSQL-ready JSONB payload type with SQLite-compatible tests.
- Alembic environment and initial migration.
- Repository layer that converts Phase 1 Pydantic domain objects to/from database records.
- Full run-state reconstruction via `RunRepository.get_full_state`.
- Persistence tests for metadata, Alembic migration, round trips, lineage, trace ordering, report evidence maps, watch/archive/thread memory, tool calls, model calls, artifacts, and review records.

Checks:

- `python -m pytest`: 20 passed.
- `python -m compileall app tests`: passed.

## Phase 3 Results

Delivered:

- Artifact service with inline, database, and file-backed storage paths.
- Deterministic artifact serialization, SHA-256 hashing, size tracking, content types, and safe file paths.
- Artifact payload reading for inline/database/file storage.
- Guardrails that reject hidden chain-of-thought style keys in structured artifact payloads.
- Trace service for phase events, agent decisions, domain object creation, tool calls, model calls, error events, and timeline reconstruction.
- Automatic trace sequence allocation per run.
- Automatic input/output/request/response artifact creation for trace, tool, and model call payloads.
- Timeline grouping helpers by phase and agent.
- Tests for artifact storage modes, hashing, redaction boundaries, trace event sequencing, call linkage, created-object refs, and timeline reconstruction.

Checks:

- `python -m pytest`: 27 passed.
- `python -m compileall app tests`: passed.

## Phase 4 Results

Delivered:

- Tool contract layer with `ToolSpec`, `ToolExecutionContext`, `RegisteredTool`, and `ToolExecutionResult`.
- Role-based `ToolRegistry`.
- `ToolExecutor` that validates `ToolEnvelope`, records tool calls, stores request/response artifacts, persists evidence, and writes trace events.
- Deterministic evidence ID generation from tool/source/item fingerprints.
- Built-in `manual_seed` tool for curated seed evidence.
- Built-in `mock_search` tool for deterministic harness and agent development.
- Tool error handling that converts exceptions or invalid envelopes into failed tool-call records and failed trace events.
- Artifact serialization support for datetime, enum, and Pydantic payloads.
- Tests for registry permission checks, duplicate registration, successful execution, evidence persistence, trace/artifact linkage, stable evidence IDs, exceptions, and invalid envelope handling.

Checks:

- `python -m pytest`: 34 passed.
- `python -m compileall app tests`: passed.

## Phase 5 Results

Delivered:

- AgentScope 2.0 added as a main dependency.
- Agent role configuration layer with role prompts, output models, execution limits, and role-specific tool names.
- Structured output schemas for Scouts, Evaluators, Writer, Reviewer, Editor, and generic agents.
- AgentScope-first `AgentRunner` that directly creates `agentscope.agent.Agent`.
- AgentScope `Toolkit` bridge that exposes Connor tools as `FunctionTool` instances.
- `ConnorFunctionTool` permission behavior that relies on Connor's role-scoped `ToolRegistry`.
- Tool calls from AgentScope execute through `ToolExecutor`, preserving `ToolCallRecord`, `EvidenceItem`, `Artifact`, and `TraceEvent` creation.
- Final AgentScope messages are parsed and validated against Connor structured output schemas.
- Tests for role registry, AgentScope tool loop execution, evidence/trace integration, invalid output rejection, and role-scoped Toolkit construction.

Checks:

- `python -m pytest tests\agents -q`: 4 passed.
- `python -m compileall app tests`: passed.
- `python -m pytest -q`: 38 passed.

## Immediate Next Step

Phase 6: Loop Harness.

Initial scope:

- Implement collect and writing state machines.
- Use AgentRunner, ToolExecutor, TraceService, and repositories under the AgentScope-first execution path.
- Add loop boundaries, budgets, phase transitions, and quality gates.
- Keep tests deterministic with AgentScope `ChatModelBase` test doubles before adding real external sources.

## Definition of Done for Each Phase

A phase is not complete until:

- The planned artifacts exist.
- Tests or checks pass.
- Documentation is updated.
- A development log entry is written.
- Any architecture decision is recorded as ADR when relevant.
