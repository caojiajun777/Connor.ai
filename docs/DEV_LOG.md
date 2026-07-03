# Connor.ai Development Log

This file is the chronological project diary. Every meaningful step should be recorded here.

Each entry should answer:

- What did we do?
- Why did we do it?
- What files changed?
- What checks did we run?
- What effect did it achieve?
- What remains open?

## 2026-07-03

### Documentation Foundation

What we did:

- Created the initial documentation archive structure.
- Added the master development plan.
- Added a progress tracker.
- Added the development log.
- Added the first architecture decision record.

Why:

- Connor.ai is intended to be traceable and replayable not only at runtime, but also during development.
- The project should preserve why each layer exists and what each step achieved.

Files changed:

- `README.md`
- `docs/MASTER_PLAN.md`
- `docs/PROGRESS.md`
- `docs/DEV_LOG.md`
- `docs/adr/0001-development-documentation-system.md`

Checks:

- Repository structure inspected before writing.
- No business code was added.

Effect:

- The project now has a written archive system and a canonical master plan.

Open follow-ups:

- Start Phase 1: Domain Schemas.
- Add schema fixtures and tests when implementation begins.


### Phase 1 Complete: Domain Schemas

What we did:

- Built the full Connor.ai domain schema layer with Pydantic v2.
- Added strict base model rules, timezone-aware datetime validation, and hidden-reasoning metadata boundaries.
- Added complete string enum coverage for runs, agents, sources, candidates, signals, evaluation decisions, watch/archive/thread lifecycle, artifacts, trace, tool/model calls, reports, and reviews.
- Added schemas for run state, evidence, candidates, event clusters, evaluation results, watchlist items, archived signals, intelligence threads, reports, trace events, artifacts, tool envelopes, tool calls, model calls, and review results.
- Added representative fixtures for Early Signal, Confirmed Event, and Tech-Finance cases.
- Added tests for serialization, validation rules, lineage relationships, report consistency, tool normalization, and trace redaction boundaries.
- Added `.gitignore` for Python and test-generated files.

Why:

- Connor.ai needs a stable domain language before database, AgentScope, tool, harness, or API work begins.
- Agent outputs must be forced into structured, auditable contracts instead of free-form summaries.
- Early Signals need intentionally looser standards than Confirmed Events, while still preserving uncertainty labels and follow-up requirements.
- Watchlist needs cost-control semantics, while Archive and Intelligence Threads preserve long-term logic-chain memory.

Files changed:

- `pyproject.toml`
- `.gitignore`
- `app/__init__.py`
- `app/domain/__init__.py`
- `app/domain/base.py`
- `app/domain/enums.py`
- `app/domain/run.py`
- `app/domain/evidence.py`
- `app/domain/candidate.py`
- `app/domain/cluster.py`
- `app/domain/evaluation.py`
- `app/domain/watchlist.py`
- `app/domain/thread.py`
- `app/domain/report.py`
- `app/domain/trace.py`
- `app/domain/artifact.py`
- `app/domain/tool.py`
- `app/domain/calls.py`
- `app/domain/review.py`
- `tests/domain/fixtures.py`
- `tests/domain/test_serialization.py`
- `tests/domain/test_validation_rules.py`
- `tests/domain/test_relationships.py`
- `docs/PROGRESS.md`
- `docs/plans/phase-01-domain-schemas.md`
- `docs/adr/0002-domain-schema-design-principles.md`
- `docs/adr/0003-watchlist-archive-thread-lifecycle.md`

Checks:

- `python -m pytest`: 16 passed.
- `python -m compileall app tests`: passed.

Effect:

- Phase 1 is complete.
- Connor.ai now has a stable domain contract that downstream database, AgentScope, harness, tool, API, and dashboard layers can reuse.

Open follow-ups:

- Start Phase 2: Database Persistence.
- Decide SQLModel vs SQLAlchemy mapping strategy.
- Define JSONB boundaries for metadata, evidence maps, score maps, and trace payload references.

### Phase 2 Complete: Database Persistence

What we did:

- Added SQLAlchemy 2.0 database foundation with declarative metadata, JSON/JSONB type helper, and session helpers.
- Added configuration support for `CONNOR_DATABASE_URL`.
- Added ORM models for all persisted Phase 1 domain objects.
- Added Alembic configuration and the initial persistence migration.
- Added repository classes that store Pydantic domain objects as query columns plus complete JSON payloads.
- Added `RunRepository.get_full_state` for reconstructing a run with its evidence, candidates, clusters, evaluations, watchlist, archives, threads, reports, trace events, calls, artifacts, and review records.
- Added database and repository tests.

Why:

- Connor.ai needs durable memory before tracing, tool execution, AgentScope integration, and report generation.
- The system needs queryable operational columns without losing the complete domain object needed for replay and audit.
- Keeping SQLAlchemy separate from Pydantic domain contracts preserves a clean architecture boundary.

Files changed:

- `pyproject.toml`
- `app/config.py`
- `app/db/base.py`
- `app/db/session.py`
- `app/db/types.py`
- `app/db/models/*`
- `app/repositories/base.py`
- `app/repositories/domain.py`
- `app/repositories/runs.py`
- `alembic.ini`
- `alembic/env.py`
- `alembic/versions/0001_initial_persistence_schema.py`
- `tests/db/test_schema_and_migrations.py`
- `tests/repositories/conftest.py`
- `tests/repositories/test_repository_persistence.py`
- `docs/PROGRESS.md`
- `docs/plans/phase-02-database-persistence.md`
- `docs/adr/0004-sqlalchemy-persistence-with-domain-payloads.md`

Checks:

- `python -m pytest`: 20 passed.
- `python -m compileall app tests`: passed.

Effect:

- Phase 2 is complete.
- Phase 1 domain objects can now be persisted, queried, restored, and reconstructed as a full run state.
- Alembic can build the persistence schema from an empty database.

Open follow-ups:

- Start Phase 3: Tracing and Artifacts.
- Build trace service APIs on top of repositories.
- Define artifact storage behavior for inline, file, database, and future object-store payloads.

### Phase 3 Complete: Tracing and Artifacts

What we did:

- Added `ArtifactService` for payload serialization, hashing, inline/database/file storage, and artifact reads.
- Added `TraceService` for phase events, agent decisions, object creation events, tool calls, model calls, error events, and timeline reconstruction.
- Added automatic per-run trace sequence allocation.
- Added automatic artifact creation for trace input/output payloads, tool request/response payloads, and model prompt/output payloads.
- Added timeline grouping by phase and agent.
- Added tests for artifact storage, hash correctness, hidden-reasoning payload rejection, trace seq ordering, call linkage, object refs, and timeline reconstruction.

Why:

- Connor.ai needs a runtime black-box layer before tools, AgentScope middleware, and loop harness are added.
- Trace rows should stay compact and audit-friendly, while raw payloads should be stored as artifacts.
- Future modules should use one trace/artifact API instead of each writing trace records differently.

Files changed:

- `app/config.py`
- `app/services/__init__.py`
- `app/services/artifacts.py`
- `app/services/tracing.py`
- `tests/conftest.py`
- `tests/services/test_artifacts.py`
- `tests/services/test_tracing.py`
- `docs/PROGRESS.md`
- `docs/plans/phase-03-tracing-and-artifacts.md`
- `docs/adr/0005-trace-and-artifact-service-boundary.md`

Checks:

- `python -m pytest`: 27 passed.
- `python -m compileall app tests`: passed.

Effect:

- Phase 3 is complete.
- Connor.ai now has a tested service layer for replayable trace writing and artifact storage.
- Future tool registry and AgentScope middleware can attach runtime activity to trace timelines without duplicating logic.

Open follow-ups:

- Start Phase 4: Tool Contract and Registry.
- Build tool execution wrappers that use `TraceService.record_tool_call`.
- Convert tool envelopes into `EvidenceItem` records through the existing domain contract.

### Phase 4 Complete: Tool Contract and Registry

What we did:

- Added the `app/tools` package.
- Added `ToolSpec`, `ToolExecutionContext`, `RegisteredTool`, and `ToolExecutionResult`.
- Added role-based `ToolRegistry`.
- Added `ToolExecutor` to validate tool envelopes, record tool calls, store request/response artifacts, persist evidence, and create trace events.
- Added deterministic evidence ID generation from tool/source/item fingerprints.
- Added built-in `manual_seed` and `mock_search` tools.
- Added tool-layer tests for registry permissions, duplicate registration, execution success, exception handling, invalid envelope handling, evidence persistence, trace linkage, artifact creation, and stable evidence IDs.
- Extended artifact serialization to support datetime, enum, and Pydantic payloads.

Why:

- Connor.ai needs a single execution boundary before real source adapters and AgentScope agents are introduced.
- Tools should not directly write database rows or trace events.
- Every source result must enter the system through `ToolEnvelope -> EvidenceItem -> TraceEvent`.

Files changed:

- `app/tools/__init__.py`
- `app/tools/base.py`
- `app/tools/registry.py`
- `app/tools/executor.py`
- `app/tools/builtin.py`
- `app/services/artifacts.py`
- `tests/tools/test_registry.py`
- `tests/tools/test_executor.py`
- `docs/PROGRESS.md`
- `docs/plans/phase-04-tool-contract-and-registry.md`
- `docs/adr/0006-tool-contract-and-execution-boundary.md`

Checks:

- `python -m pytest`: 34 passed.
- `python -m compileall app tests`: passed.

Effect:

- Phase 4 is complete.
- Connor.ai now has a tested tool registration and execution layer.
- Future AgentScope agents can receive role-specific tools and execute them through one traceable, evidence-producing path.

Open follow-ups:

- Start Phase 5: AgentScope Integration.
- Bind `ToolRegistry.list_for_agent` into Agent role configuration.
- Map AgentScope tool events into `TraceService` without duplicating tool execution logic.

### Phase 5 Initial Attempt: Superseded Runtime Boundary

What we did:

- Added the `app/agents` package.
- Added role configuration, default prompts, runtime limits, and role-specific tool binding.
- Added structured output schemas for Scouts, Evaluators, Writer, Reviewer, Editor, and generic agents.
- Added an `AgentRuntime` protocol.
- Added `DeterministicAgentRuntime` for tests and local harness development.
- Added optional `AgentScopeRuntime` with lazy imports and clear missing-package behavior.
- Added `AgentRunner` to record agent start/completion/error traces, validate structured output, and execute requested tools through `ToolExecutor`.
- Added tests for role registry, agent runner execution, tool/evidence/trace integration, invalid output rejection, tool permission enforcement, and missing AgentScope behavior.
- Added optional `agentscope` dependency extra in `pyproject.toml`.

Why:

- Connor.ai needs AgentScope integration without giving AgentScope ownership of product state, persistence, tool execution, or trace writing.
- The local environment did not have AgentScope installed, so the integration boundary must remain testable through a deterministic runtime.
- Future loop harness code should call one AgentRunner API regardless of runtime.

Files changed:

- `pyproject.toml`
- `app/agents/__init__.py`
- `app/agents/config.py`
- `app/agents/outputs.py`
- `app/agents/prompts.py`
- `app/agents/registry.py`
- `app/agents/runtime.py`
- `app/agents/deterministic.py`
- `app/agents/agentscope_adapter.py`
- `app/agents/runner.py`
- `tests/agents/test_registry.py`
- `tests/agents/test_runner.py`
- `tests/agents/test_agentscope_adapter.py`
- `docs/PROGRESS.md`
- `docs/plans/phase-05-agentscope-integration.md`
- `docs/adr/0007-agent-runtime-boundary.md`

Checks:

- `python -m pytest`: 39 passed.
- `python -m compileall app tests`: passed.

Effect:

- This approach was implemented and tested, but then rejected during review.
- The flaw was architectural: it made AgentScope optional and introduced a Connor-owned agent runtime contract.
- The final Phase 5 design below supersedes this attempt.

Open follow-ups:

- Replace the runtime-boundary design with an AgentScope-first implementation.

### Phase 5 Corrected Complete: AgentScope-First Integration

What we did:

- Installed and promoted `agentscope>=2.0` to a main project dependency.
- Verified the local AgentScope 2.0 API for `Agent`, `ReActConfig`, `Toolkit`, `FunctionTool`, `Msg`, `UserMsg`, `ToolCallBlock`, `ToolResponse`, and `ChatModelBase`.
- Removed the Connor-owned `AgentRuntime` protocol.
- Removed `DeterministicAgentRuntime`.
- Removed the optional lazy `AgentScopeRuntime` adapter.
- Added `AgentRunRequest`, `AgentRunResult`, and `AgentScopeExecutionError` as runner I/O schemas, not as a runtime contract.
- Added `AgentScopeToolBridge` and `ConnorFunctionTool`.
- Rewrote `AgentRunner` so it directly creates AgentScope `Agent` with AgentScope `Toolkit`.
- Ensured AgentScope tool calls execute through Connor `ToolExecutor`, preserving evidence, tool-call records, artifacts, and trace events.
- Rewrote agent tests to use a deterministic AgentScope `ChatModelBase` test double.
- Added a test where AgentScope returns a `ToolCallBlock`, calls a Connor tool through `Toolkit`, receives tool results, and then emits final structured JSON.
- Updated Phase 5 plan, ADR 0007, progress tracker, and master plan.

Why:

- AgentScope is Connor.ai's first-choice agent framework, not an optional backend.
- Connor loop harness should control run state, loop boundaries, quality gates, artifacts, and trace persistence.
- AgentScope should control agent execution, tool-call mechanics, event stream, middleware, and future team/worker organization.
- Testing should stay deterministic by using AgentScope's official model interface, not by bypassing AgentScope.

Files changed:

- `pyproject.toml`
- `app/agents/__init__.py`
- `app/agents/config.py`
- `app/agents/registry.py`
- `app/agents/schemas.py`
- `app/agents/agentscope_tools.py`
- `app/agents/runner.py`
- `tests/agents/test_runner.py`
- `docs/MASTER_PLAN.md`
- `docs/PROGRESS.md`
- `docs/plans/phase-05-agentscope-integration.md`
- `docs/adr/0007-agent-runtime-boundary.md`
- `docs/DEV_LOG.md`

Files removed:

- `app/agents/runtime.py`
- `app/agents/deterministic.py`
- `app/agents/agentscope_adapter.py`
- `tests/agents/test_agentscope_adapter.py`

Checks:

- `python -m pytest tests\agents -q`: 4 passed.
- `python -m compileall app tests`: passed.
- `python -m pytest -q`: 38 passed.

Effect:

- Phase 5 is now complete in the intended AgentScope-first form.
- Connor.ai no longer has a custom agent runtime contract.
- AgentScope `Agent.reply(...)` and AgentScope `Toolkit` are on the tested execution path.
- Connor tool execution, evidence persistence, artifact archival, and trace writing remain unified through the existing Phase 4 and Phase 3 services.

Open follow-ups:

- Start Phase 6: Loop Harness on top of the corrected AgentScope-first `AgentRunner`.
- Add AgentScope event-stream middleware tracing when the harness starts using streamed events.
- Add real model provider configuration after loop boundaries and quality gates are stable.

### Phase 6 Complete: Loop Harness

What we did:

- Added the `app/harness` package.
- Added `HarnessConfig` for loop limits and quality thresholds.
- Added `HarnessContext` for shared repositories, trace service, artifact service, run updates, phase transitions, failure handling, and snapshot archival.
- Added `AgentTask`, `CollectGateDecision`, `WritingGateDecision`, and `DailyRunResult`.
- Added `QualityGateService` for deterministic collect and writing gate decisions.
- Added `CollectLoopHarness` with bounded collect rounds, AgentScope task dispatch, gate decisions, follow-up, recluster, manual review, and failure paths.
- Added `WritingLoopHarness` with Writer, Reviewer, Editor, final review, revision budget, reopen collect, manual review, failure, and finalization paths.
- Added `DailyRunHarness` for creating, running, and resuming daily runs.
- Added harness trace events for run start, phase start/completion, gate decisions, final report acceptance, and errors.
- Added artifact snapshots for collect gate decisions, writing gate decisions, and final report payloads.
- Added Phase 6 tests for quality gates, collect loop, writing loop, and full daily run finalization.
- Added Phase 6 plan documentation and ADR 0008.

Why:

- AgentScope should control agent execution, while Connor needs deterministic product control around run lifecycle, loop boundaries, quality gates, artifact archival, and trace persistence.
- A long-running daily intelligence system must be bounded and replayable before adding more sources or more autonomous agent behavior.
- Gate decisions should be structured and auditable rather than hidden in prompts.

Files changed:

- `app/harness/__init__.py`
- `app/harness/config.py`
- `app/harness/context.py`
- `app/harness/decisions.py`
- `app/harness/exceptions.py`
- `app/harness/gates.py`
- `app/harness/collect.py`
- `app/harness/writing.py`
- `app/harness/runner.py`
- `tests/harness/__init__.py`
- `tests/harness/helpers.py`
- `tests/harness/test_quality_gates.py`
- `tests/harness/test_collect_loop.py`
- `tests/harness/test_writing_loop.py`
- `tests/harness/test_daily_run_harness.py`
- `docs/MASTER_PLAN.md`
- `docs/PROGRESS.md`
- `docs/plans/phase-06-loop-harness.md`
- `docs/adr/0008-loop-harness-control-boundary.md`
- `docs/DEV_LOG.md`

Checks:

- `python -m pytest tests\harness -q`: 7 passed.
- `python -m pytest -q`: 45 passed.
- `python -m compileall app tests`: passed.

Effect:

- Phase 6 is complete.
- Connor.ai now has a tested loop harness that controls run state, collect loop, writing loop, quality gates, loop budgets, trace, and artifact snapshots.
- Agent tasks in the harness still route through the AgentScope-first `AgentRunner`.
- Future phases can add real Scout, Clusterer, Evaluator, Watchlist, Writer, Reviewer, and Editor behavior without rewriting run control.

Open follow-ups:

- Start Phase 7: Single-Agent Closed Loop.
- Build one real Scout path inside the harness.
- Convert one AgentScope agent output into persisted evidence and candidate objects.
- Add richer AgentScope event-stream tracing once streamed execution is used.

### Phase 7 Complete: Single-Agent Closed Loop

What we did:

- Added `CandidateDraft` to the agent output layer.
- Extended `ScoutOutput` with `candidate_drafts`.
- Added `ScoutOutputMaterializer` in `app/harness/materialization.py`.
- Connected Scout output materialization into `CollectLoopHarness`.
- Added harness config flags for Scout candidate materialization and single-agent bootstrap.
- Implemented candidate persistence from Scout structured output.
- Implemented marked provisional cluster and evaluation creation when no explicit Clusterer/Evaluator tasks are scheduled.
- Updated run lineage with generated candidate and cluster ids.
- Added trace events for candidate, cluster, and evaluation creation.
- Added a Phase 7 closed-loop test using AgentScope `ToolCallBlock`, Connor `manual_seed`, `ToolExecutor`, `EvidenceItem`, Scout `candidate_drafts`, materialization, and collect gate entry into writing.
- Added Phase 7 plan documentation and ADR 0009.

Why:

- Phase 6 proved loop control using preloaded domain state. Phase 7 needed to prove an AgentScope Scout can create new persisted Connor domain state through the real tool and trace boundaries.
- Agents should propose candidates, but Connor should validate and persist them through a materialization boundary.
- The single-agent bootstrap cluster/evaluation path lets the collect gate close one full loop before the production Clusterer and Evaluator phases are implemented.

Files changed:

- `app/agents/__init__.py`
- `app/agents/outputs.py`
- `app/harness/__init__.py`
- `app/harness/collect.py`
- `app/harness/config.py`
- `app/harness/materialization.py`
- `tests/harness/test_single_agent_closed_loop.py`
- `docs/MASTER_PLAN.md`
- `docs/PROGRESS.md`
- `docs/plans/phase-07-single-agent-closed-loop.md`
- `docs/adr/0009-scout-output-materialization.md`
- `docs/DEV_LOG.md`

Checks:

- `python -m pytest tests\harness -q`: 8 passed.
- `python -m pytest -q`: 46 passed.
- `python -m compileall app tests`: passed.

Effect:

- Phase 7 is complete.
- Connor.ai now has one tested AgentScope Scout closed loop from tool call to evidence, candidate, provisional cluster/evaluation, collect gate, trace, and persistence.
- The bootstrap records are explicitly marked with `bootstrap_single_agent: true`, preserving the boundary for later production Clusterer/Evaluator work.

Open follow-ups:

- Start Phase 8: All Scouts.
- Add role-specific candidate draft expectations for Social, Code & Model, Research, Official, and Finance Scouts.
- Replace bootstrap clustering/evaluation with full Clusterer and Evaluator agents in Phases 9 and 10.
