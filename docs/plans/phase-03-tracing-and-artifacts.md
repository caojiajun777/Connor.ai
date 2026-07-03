# Phase 3 Plan: Tracing and Artifacts

Status: Complete

Completed: 2026-07-03

## Goal

Build the runtime service layer that records what Connor.ai does and stores large or raw payloads without polluting primary trace records.

Phase 3 answers:

```text
How does Connor.ai record a replayable run timeline?
How are raw inputs, outputs, tool responses, model payloads, and trace payloads stored?
```

## Delivered Architecture

Added:

```text
app/services/
  artifacts.py
  tracing.py
```

The service layer sits above repositories:

```text
Domain Schemas
-> Repositories
-> ArtifactService / TraceService
-> Future AgentScope middleware, tool registry, harness, writer, reviewer
```

## ArtifactService

Responsibilities:

- Serialize payloads consistently.
- Compute SHA-256 hashes.
- Track payload size and content type.
- Store small structured/text payloads inline.
- Store large or binary payloads as files.
- Support explicit database payload storage.
- Reject structured payload keys that imply hidden chain-of-thought storage.
- Return and read persisted `Artifact` domain objects.

Supported storage paths:

- `ArtifactStorage.INLINE`
- `ArtifactStorage.DATABASE`
- `ArtifactStorage.FILE`

Reserved for later:

- `ArtifactStorage.OBJECT_STORE`

## TraceService

Responsibilities:

- Record phase start/completion events.
- Record agent decisions with reasoning summaries only.
- Record domain object creation events.
- Record tool calls and model calls.
- Store request/response/prompt/output payloads as artifacts.
- Link trace events to tool/model call records.
- Assign monotonic trace `seq` values per run.
- Reconstruct a timeline with linked tool calls, model calls, and artifacts.

Key APIs:

- `record_event`
- `phase_started`
- `phase_completed`
- `agent_decision`
- `object_created`
- `record_tool_call`
- `record_model_call`
- `reconstruct_timeline`

## Trace Boundary

Trace events store:

- What happened.
- Which phase.
- Which agent.
- Which tool/model call.
- Which objects were created.
- Summary and reasoning summary.
- Error and duration.
- Artifact references for larger payloads.

Trace events do not store full hidden reasoning.

Large or raw payloads go into artifacts and are referenced from trace events or call records.

## Tests Delivered

Test files:

- `tests/services/test_artifacts.py`
- `tests/services/test_tracing.py`

Coverage:

- Inline artifact storage and reading.
- File-backed binary artifact storage and reading.
- Database payload artifact storage and reading.
- SHA-256 hashing.
- Hidden-reasoning key rejection in structured artifact payloads.
- Trace seq allocation across multiple events before commit.
- Phase events.
- Agent decision events.
- Domain object creation refs.
- Tool call records linked to trace events and artifacts.
- Model call records linked to trace events and artifacts.
- Timeline reconstruction with phase and agent grouping.
- Failed trace events and failed-call validation boundaries.

## Checks Run

- `python -m pytest`: 27 passed.
- `python -m compileall app tests`: passed.

## Non-Goals Preserved

- No AgentScope middleware yet.
- No tool registry yet.
- No real external source adapters.
- No loop harness.
- No FastAPI endpoints.

## Follow-up Phase

Phase 4 should implement Tool Contract and Registry on top of this tracing/artifact service layer.

