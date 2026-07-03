# ADR 0006: Tool Contract and Execution Boundary

Date: 2026-07-03

Status: Accepted

## Context

Connor.ai will eventually use many heterogeneous tools: social search, GitHub, Hugging Face, arXiv, official changelogs, SEC filings, investor relations, and paid sources.

If each tool writes evidence, trace events, artifacts, and tool-call records differently, the system will become difficult to replay and audit.

Phase 4 needed one execution boundary that future AgentScope agents and harness code can reuse.

## Decision

All tools must be registered through `ToolRegistry` and executed through `ToolExecutor`.

Every tool returns `ToolEnvelope`.

`ToolExecutor` is responsible for:

- Role-based tool permission checks.
- Envelope validation.
- Tool-call record persistence.
- Request and response artifact storage.
- Evidence normalization and persistence.
- Trace event creation.
- Error normalization.

Tools themselves should focus on source-specific retrieval and normalization into `ToolEnvelope`.
They should not directly write database rows or trace events.

## Consequences

Benefits:

- Future source adapters share one contract.
- Agent role permissions are centralized.
- Evidence lineage is consistently created from tool results.
- Tool failures become traceable records instead of unstructured exceptions.
- Tool response payloads are archived automatically.

Costs:

- Source adapters must conform to `ToolEnvelope`.
- The executor owns more orchestration logic and must remain well tested.
- Real network tools will need timeout/retry policies in later phases.

## Validation

Phase 4 delivered tests for registry behavior, role permissions, successful execution, evidence persistence, trace/artifact linkage, stable evidence IDs, exception handling, and invalid envelope handling.

