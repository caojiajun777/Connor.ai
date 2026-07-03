# ADR 0002: Domain Schema Design Principles

Date: 2026-07-03

Status: Accepted

## Context

Connor.ai relies on multiple autonomous agents, tools, evaluators, writing loops, and future dashboard/API consumers. Without a stable domain contract, agent output can become free-form and hard to persist, replay, audit, or render.

The domain layer must be created before database persistence, AgentScope integration, source tools, and API endpoints.

## Decision

Connor.ai will define a framework-independent domain schema layer using Pydantic v2.

Principles:

- Schemas are independent of database models and AgentScope runtime objects.
- All enums are JSON-friendly string enums.
- Core entities carry `schema_version`.
- All datetimes must be timezone-aware.
- Models reject unknown extra fields.
- Business-critical fields are explicit; flexible data goes into `metadata`.
- Metadata may not contain keys that imply hidden chain-of-thought storage.
- Tool outputs, agent outputs, evaluation decisions, report items, and traces all land in explicit schemas.

The main lineage path is:

```text
EvidenceItem
-> CandidateItem
-> EventCluster
-> EvaluationResult
-> WatchlistItem / ArchivedSignal / DailyReport
-> IntelligenceThread
```

Trace and artifact objects run alongside this lineage:

```text
TraceEvent
-> ToolCallRecord / ModelCallRecord / Artifact
```

## Consequences

Benefits:

- Agent output can be validated before entering the system.
- Database and API layers can be designed against stable contracts.
- Tests can enforce domain rules before runtime complexity appears.
- Dashboard JSON can reuse report and lineage structures.

Costs:

- Schema changes should now be treated as compatibility decisions.
- Later database work must map these contracts carefully instead of inventing parallel shapes.

## Validation

Phase 1 delivered serialization, validation, and relationship tests over representative Early Signal, Confirmed Event, and Tech-Finance fixtures.