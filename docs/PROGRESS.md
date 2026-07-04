# Connor.ai Progress Tracker

Last updated: 2026-07-04

## Current Status

Project state: Phase 13 complete. Connor.ai now exposes a FastAPI dashboard contract for runs, reports, trace timelines, clusters, watchlist items, and intelligence threads.

Next phase: Phase 14, Source Expansion.

## Phase Progress

| Phase | Name | Status | Notes |
|---|---|---|---|
| 1 | Domain Schemas | Complete | Full Pydantic domain contract, fixtures, validation tests, and ADRs delivered. |
| 2 | Database Persistence | Complete | SQLAlchemy ORM, Alembic migration, repositories, and persistence tests delivered. |
| 3 | Tracing and Artifacts | Complete | ArtifactService, TraceService, timeline reconstruction, and service tests delivered. |
| 4 | Tool Contract and Registry | Complete | ToolSpec, ToolRegistry, ToolExecutor, manual seed/mock tools, evidence normalization, and tool tests delivered. |
| 5 | AgentScope Integration | Complete | AgentScope is a main dependency; AgentRunner uses AgentScope Agent/Toolkit/FunctionTool directly. |
| 6 | Loop Harness | Complete | DailyRunHarness, collect loop, writing loop, quality gates, budgets, trace, and artifact snapshots delivered. |
| 7 | Single-Agent Closed Loop | Complete | One Social Scout path now runs through AgentScope tool call, evidence, candidate materialization, bootstrap cluster/evaluation, and collect gate. |
| 8 | All Scouts | Complete | Five Scout profiles, task templates, prompt constraints, materialization validation, and all-Scout closed-loop tests delivered. |
| 9 | Clusterer | Complete | ClustererOutput, ClusterOutputMaterializer, dedupe merge, confirmation links, conflict preservation, and closed-loop tests delivered. |
| 10 | Evaluator Group | Complete | Frontier/Event/Market profiles, evaluation drafts, materialization, trace, and closed-loop test delivered. |
| 11 | Watchlist + Archive + Intelligence Threads | Complete | Watchlist Agent output, lifecycle service, TTL archive, thread updates, and closed-loop test delivered. |
| 12 | Writing Loop | Complete | Writer/Reviewer/Editor draft materialization, report JSON/markdown/evidence map generation, reviewer uncertainty guard, and closed-loop tests delivered. |
| 13 | FastAPI and Dashboard Contract | Complete | FastAPI app, dashboard response schemas, run/report/trace/cluster/watchlist/thread endpoints, and API tests delivered. |
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

## Phase 6 Results

Delivered:

- `app/harness` package with config, context, decisions, exceptions, gates, collect loop, writing loop, and daily runner.
- `DailyRunHarness` for create, run, and resume.
- `CollectLoopHarness` with bounded collect rounds and gate outcomes for writing, follow-up, recluster, continue, manual review, and failure.
- `WritingLoopHarness` with bounded writing/review rounds and outcomes for finalize, review draft, revise, reopen collect, manual review, and failure.
- `QualityGateService` for deterministic collect and writing gate decisions.
- Harness trace events for run start, phase start/completion, gate decisions, report finalization, and failures.
- Harness artifact snapshots for collect gate decisions, writing gate decisions, and final report payloads.
- Tests for gates, collect loop, writing revision loop, and top-level daily run finalization.

Checks:

- `python -m pytest tests\harness -q`: 7 passed.
- `python -m pytest -q`: 45 passed.
- `python -m compileall app tests`: passed.

## Phase 7 Results

Delivered:

- `CandidateDraft` schema and `ScoutOutput.candidate_drafts`.
- `ScoutOutputMaterializer` for converting Scout outputs into persisted `CandidateItem` records.
- Single-agent bootstrap creation of marked provisional `EventCluster` and `EvaluationResult` records when no explicit Clusterer/Evaluator tasks are scheduled.
- Collect loop integration that materializes AgentScope Scout results after tool execution.
- Run lineage updates for generated candidate and cluster ids.
- Trace events for candidate, cluster, and evaluation creation.
- Phase 7 test proving AgentScope `ToolCallBlock -> manual_seed -> EvidenceItem -> CandidateItem -> EventCluster -> EvaluationResult -> collect gate enter_writing`.

Checks:

- `python -m pytest tests\harness -q`: 8 passed.
- `python -m pytest -q`: 46 passed.
- `python -m compileall app tests`: passed.

## Phase 8 Results

Delivered:

- `app/scouts` package with Scout profiles and task construction.
- Role profiles for Social Scout, Code & Model Scout, Research Scout, Official Scout, and Finance Scout.
- Source-type, category, signal-status, follow-up, official-evidence, and finance-impact validation rules.
- Scout profile prompt extensions wired into `create_default_agent_role_registry`.
- `ScoutTaskFactory` for role-specific `AgentTask` creation with profile context and candidate output contract.
- Materialization-time profile validation in `ScoutOutputMaterializer`.
- Candidate metadata that records the producing Scout profile.
- Lazy `ScoutTaskFactory` export to avoid circular imports between AgentScope registry and harness task construction.
- Tests for profile registry coverage, task creation, invalid profile rejection, and all five Scout closed loops through AgentScope tool calls.

Checks:

- `python -m pytest tests\scouts tests\harness\test_all_scouts_closed_loop.py tests\harness\test_single_agent_closed_loop.py tests\agents\test_registry.py -q`: 8 passed.
- `python -m pytest -q`: 52 passed.
- `python -m compileall app tests`: passed.

## Phase 9 Results

Delivered:

- `ClusterTimelineDraft`, `ClusterDraft`, and `ClustererOutput` structured output schemas.
- Agent registry binding for `AgentRole.CLUSTERER -> ClustererOutput`.
- `app/clusterer` package with `ClusterOutputMaterializer` and `ClusterTaskFactory`.
- Candidate context construction for Clusterer tasks.
- Collect loop integration for the clustering phase.
- Materialization validation for candidate existence and run ownership.
- Evidence lineage expansion from candidate evidence ids.
- Deterministic cluster id generation.
- Agent-provided and fallback dedupe-key behavior.
- Dedupe-key merge that preserves candidates, evidence, timeline, entities, tickers, topics, conflict summary, and metadata.
- Early-signal to official-confirmation link metadata.
- Temporary marked `bootstrap_clusterer_evaluation` bridge when no Evaluator task is scheduled.
- Tests for materialization, dedupe merge, missing candidate rejection, agent registry binding, and a Scout-to-Clusterer AgentScope closed loop.

Checks:

- `python -m pytest tests\clusterer tests\harness\test_clusterer_closed_loop.py tests\agents\test_registry.py -q`: 5 passed.
- `python -m pytest -q`: 56 passed.
- `python -m compileall app tests`: passed.

## Phase 10 Results

Delivered:

- `EvaluationDraft` structured output for evaluator agents.
- `EvaluatorOutput.evaluation_drafts` support while preserving backward compatibility with existing evaluation ids and decisions.
- `app/evaluators` package with role profiles, task factory, compact cluster context, and materializer.
- Frontier Evaluator profile for looser early-signal selection based on information gap, specificity, source proximity, potential impact, and trackability.
- Event Evaluator profile for confirmed events and official updates with strict `select_confirmed` requirements.
- Market Evaluator profile for tech-finance clusters with AI relevance, market impact, supply-chain impact, and ticker relevance.
- Evaluator profile prompt extensions wired into `create_default_agent_role_registry`.
- `EvaluatorOutputMaterializer` for validating drafts, creating `EvaluationResult` records, marking selected clusters, updating run metadata, and writing `EVALUATION_CREATED` trace events.
- Collect loop integration for evaluator materialization and `cluster_context` injection.
- Harness config flag `materialize_evaluator_outputs`.
- Tests for evaluator profiles, task context, materialization, invalid draft rejection, prompt wiring, and AgentScope Frontier Evaluator closed loop.

Checks:

- `python -m pytest tests\evaluators tests\harness\test_evaluator_closed_loop.py tests\agents\test_registry.py -q`: 10 passed.
- `python -m pytest -q`: 71 passed.
- `python -m compileall app tests`: passed.

## Phase 11 Results

Delivered:

- `WatchlistDraft`, `ArchiveDraft`, `ThreadTimelineDraft`, `ThreadDraft`, and `WatchlistAgentOutput`.
- Agent registry binding for `AgentRole.WATCHLIST_AGENT -> WatchlistAgentOutput`.
- `app/watchlist` package with task construction, compact memory context, materialization, and lifecycle policy.
- Watchlist Agent prompt extension for cost-aware memory, TTLs, archive, and intelligence threads.
- `WatchlistOutputMaterializer` for validating lineage, creating/updating watchlist items, archiving signals, creating/updating threads, updating run lineage, and writing trace events.
- `WatchlistLifecycleService` for automatic due-watch expiration and deterministic evaluator-memory sync when no Watchlist Agent task is scheduled.
- Collect loop integration for `WATCHLIST_UPDATE` materialization, due expiration, memory-context injection, and evaluator-memory fallback.
- Harness config flags for watchlist materialization, due expiration, and evaluator-memory auto-sync.
- Trace object mapping for WatchlistItem, ArchivedSignal, and IntelligenceThread.
- Centralized ID prefixes for watch, archive, and thread records.
- Collect-gate metrics for watchlist, archive, and thread counts.
- Tests for materialization, lifecycle, AgentScope Watchlist Agent closed loop, and registry prompt wiring.

Checks:

- `python -m pytest tests\watchlist tests\harness\test_watchlist_closed_loop.py tests\agents\test_registry.py -q`: 6 passed.
- `python -m pytest -q`: 76 passed.
- `python -m compileall app tests`: passed.

## Phase 12 Results

Delivered:

- `ReportItemDraft`, `ReportSectionDraft`, `ReportDraft`, `ReviewIssueDraft`, and `ReviewDraft` structured outputs.
- `WriterOutput`, `ReviewerOutput`, and `EditorOutput` support for materializable drafts while preserving backward compatibility with existing id-based outputs.
- `app/writing` package with `WritingOutputMaterializer` and `WritingTaskFactory`.
- Writer draft materialization into `DailyReport` records.
- Editor revised draft materialization into updated `DailyReport` records.
- Reviewer draft materialization into `ReviewResult` and `ReviewIssue` records.
- Automatic `full_markdown` rendering when agents do not provide markdown.
- Automatic `full_json`, `evidence_map`, `watchlist_updates`, and `trace_timeline_ids` generation.
- Report trace backfill so materialized reports include the trace event that created or edited them.
- Deterministic Reviewer guard that converts invalid PASS reviews into REVISE when early signals use confirmed-fact language.
- Writing-loop context injection for Writer, Reviewer, and Editor tasks.
- Harness config flag `materialize_writing_outputs`.
- Centralized ID prefixes for report, review, and issue records.
- Tests for materialization, uncertainty guard, editor revisions, and a no-side-effect AgentScope-style writing loop.

Checks:

- `python -m pytest tests\writing\test_materialization.py tests\harness\test_writing_loop.py -q`: 6 passed.
- `python -m pytest -q`: 88 passed.
- `python -m compileall app tests`: passed.
- `git diff --check`: passed.

## Phase 13 Results

Delivered:

- FastAPI dependency declarations.
- `app/api` package with app factory, routes, dependencies, and public schemas.
- ASGI entrypoint at `app/main.py`.
- `POST /runs/daily` for scheduled run creation.
- `GET /runs/{run_id}` for dashboard-ready full run state.
- `GET /runs/{run_id}/trace` for replayable trace timelines.
- `GET /runs/{run_id}/clusters` for run cluster lists.
- `GET /reports/{report_id}` for markdown, dashboard JSON, evidence map, watchlist updates, and trace IDs.
- `GET /watchlist` with optional status/run filtering.
- `GET /threads` and `GET /threads/{thread_id}`.
- Repository `list_all` helper and stable status-query ordering.
- API tests using FastAPI `TestClient` and thread-safe SQLite `StaticPool`.
- Phase 13 plan and ADR 0015.

Checks:

- `python -m pytest tests\api\test_routes.py -q`: 3 passed.
- `python -m pytest -q`: 91 passed.
- `python -m compileall app tests`: passed.
- `git diff --check`: passed.

## Immediate Next Step

Phase 14: Source Expansion.

Initial scope:

- Add real source connectors in a controlled order.
- Start with GitHub / Hugging Face because they fit current evidence and code/model scout contracts.
- Preserve the same tool envelope, evidence, artifact, and trace boundaries.

## Definition of Done for Each Phase

A phase is not complete until:

- The planned artifacts exist.
- Tests or checks pass.
- Documentation is updated.
- A development log entry is written.
- Any architecture decision is recorded as ADR when relevant.
