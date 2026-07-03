# Phase 1 Plan: Domain Schemas

Status: Complete

Completed: 2026-07-03

## Goal

Define Connor.ai's core domain language before implementing agents, tools, persistence, or APIs.

The output of this phase makes it clear what kinds of objects the system creates, validates, serializes, and passes between components.

## Delivered Scope

Created schema definitions for:

- `RunState`
- `EvidenceItem`
- `CandidateItem`
- `EventCluster`
- `EvaluationResult`
- `WatchlistItem`
- `ArchivedSignal`
- `IntelligenceThread`
- `DailyReport`
- `TraceEvent`
- `Artifact`
- `ToolCallRecord`
- `ModelCallRecord`
- `ReviewResult`
- `ToolEnvelope`
- `ToolEnvelopeItem`
- `ReportSection`
- `ReportItem`

Created enum definitions for:

- Run phase and status.
- Agent role.
- Source type and source access level.
- Candidate category and signal status.
- Evidence strength and confidence.
- Evaluation type and decision.
- Watch tier and watch status.
- Thread status and later outcome.
- Archive reason.
- Artifact kind and storage.
- Trace event type and trace status.
- Tool call and model call status.
- Report status and review decision.
- Object type references.

## Key Design Rules Implemented

- Domain schemas are independent of database and AgentScope runtime.
- All enums are JSON-friendly string enums.
- Core domain objects carry `schema_version`.
- Datetimes must be timezone-aware.
- Models forbid unknown extra fields.
- Metadata rejects keys that imply hidden chain-of-thought storage.
- Early Signals may be low confidence, but must have a non-confirmed signal status and follow-up questions.
- Confirmed Events require strong or official evidence.
- Watchlist items enforce tier-specific TTL limits.
- Archived signals require lineage to an original cluster or watch item.
- Intelligence thread timeline entries require linked objects.
- Final reports require Markdown, sections, evidence maps, and trace timeline IDs.
- Tool envelopes can normalize result items into `EvidenceItem` objects.

## Delivered Tests

Test files:

- `tests/domain/test_serialization.py`
- `tests/domain/test_validation_rules.py`
- `tests/domain/test_relationships.py`

Coverage areas:

- JSON serialization / deserialization.
- Enum JSON compatibility.
- Required field validation.
- Candidate evidence rules.
- Early Signal loosened standards.
- Confirmed Event stronger evidence rules.
- Evaluation decision requirements.
- Watchlist TTL rules.
- Archive lineage rules.
- Intelligence Thread timeline links.
- Report schema consistency.
- ToolEnvelope to EvidenceItem normalization.
- Trace metadata redaction boundary.

## Checks Run

- `python -m pytest`: 16 passed.
- `python -m compileall app tests`: passed.

## Non-Goals Preserved

- No database models yet.
- No AgentScope integration yet.
- No real source tools yet.
- No report generation runtime yet.

## Follow-up Phase

Phase 2 should implement database persistence based on these domain contracts.