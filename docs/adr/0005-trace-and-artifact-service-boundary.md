# ADR 0005: Trace and Artifact Service Boundary

Date: 2026-07-03

Status: Accepted

## Context

Connor.ai must preserve a replayable execution history without storing full hidden reasoning or bloating trace rows with large raw payloads.

Phase 1 defined `TraceEvent`, `Artifact`, `ToolCallRecord`, and `ModelCallRecord`.
Phase 2 made those objects persistent.
Phase 3 needed a service boundary so future AgentScope middleware, tool adapters, harness code, and writing/review loops can all record runtime activity consistently.

## Decision

Introduce two services:

- `ArtifactService`: owns payload serialization, hashing, storage selection, and artifact reads.
- `TraceService`: owns trace event creation, sequence allocation, call records, object refs, and timeline reconstruction.

Trace records store summaries and references.
Artifacts store raw or large payloads.

Structured artifact payloads reject keys such as `chain_of_thought`, `cot`, `full_reasoning`, `hidden_reasoning`, and `private_reasoning` by default.

## Consequences

Benefits:

- Future modules do not hand-roll trace writes.
- Trace timeline ordering is centralized.
- Tool/model payloads are consistently attached as artifacts.
- Runtime replay can join trace events, tool calls, model calls, artifacts, and created object refs.
- Hidden reasoning storage is blocked at both TraceEvent and ArtifactService boundaries.

Costs:

- Services need to be passed into future runtime layers.
- Artifact storage policy must evolve when object-store support is added.
- Concurrent trace writers may need database-level sequencing in a later worker phase.

## Validation

Phase 3 delivered service tests for artifact storage modes, trace sequencing, call linkage, object refs, and timeline reconstruction.

