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

### Phase 8 Complete: All Scouts

What we did:

- Added the `app/scouts` package.
- Added `ScoutProfile`, `ScoutProfileRegistry`, and `ScoutProfileError`.
- Added default profiles for Social Scout, Code & Model Scout, Research Scout, Official Scout, and Finance Scout.
- Added `ScoutTaskFactory` for role-specific `AgentTask` construction.
- Added Scout profile prompt extensions to the AgentScope role registry.
- Added materialization-time validation so each Scout's `CandidateDraft` is checked before `CandidateItem` persistence.
- Added candidate metadata that records the producing Scout profile.
- Added lazy `ScoutTaskFactory` export in `app/scouts/__init__.py` to avoid a circular import between agent registry and harness task construction.
- Added profile tests and all-Scout AgentScope closed-loop tests.

Why:

- Phase 7 proved one Scout path, but Connor.ai needs five distinct Scout roles before real source expansion.
- We wanted role-specific boundaries without creating a custom agent runtime contract.
- Early signals should stay permissive, while official and finance items need stricter validation.
- The harness should reject invalid Scout output before it becomes persisted intelligence state.

Files changed:

- `app/scouts/__init__.py`
- `app/scouts/profiles.py`
- `app/scouts/tasks.py`
- `app/agents/registry.py`
- `app/harness/materialization.py`
- `tests/scouts/__init__.py`
- `tests/scouts/test_profiles.py`
- `tests/harness/test_all_scouts_closed_loop.py`
- `docs/MASTER_PLAN.md`
- `docs/PROGRESS.md`
- `docs/plans/phase-08-all-scouts.md`
- `docs/adr/0010-scout-profile-boundaries.md`
- `docs/DEV_LOG.md`

Checks:

- `python -m pytest tests\scouts tests\harness\test_all_scouts_closed_loop.py tests\harness\test_single_agent_closed_loop.py tests\agents\test_registry.py -q`: 8 passed.
- `python -m pytest -q`: 52 passed.
- `python -m compileall app tests`: passed.

Effect:

- Phase 8 is complete.
- All five Scout roles now have explicit role profiles, prompt/task constraints, and materialization validation.
- All five Scouts can run through AgentScope, call Connor tools, produce candidate drafts, create candidates, create bootstrap clusters/evaluations, and pass the collect gate.
- Invalid profile output is blocked before persistence.

Open follow-ups:

- Start Phase 9: Clusterer.
- Replace bootstrap cluster creation with production clustering.
- Add canonical claim generation, dedupe keys, conflict preservation, and early-signal-to-confirmation linking.

### Phase 9 Complete: Clusterer

What we did:

- Added Clusterer-specific structured outputs: `ClusterTimelineDraft`, `ClusterDraft`, and `ClustererOutput`.
- Bound `AgentRole.CLUSTERER` to `ClustererOutput` in the agent registry.
- Added `app/clusterer` with `ClusterOutputMaterializer` and `ClusterTaskFactory`.
- Added candidate context construction so the collect loop can pass compact candidate/evidence summaries into Clusterer tasks.
- Connected Clusterer materialization into `CollectLoopHarness`.
- Added cluster draft validation against persisted candidates and run ownership.
- Added evidence lineage expansion from candidate evidence ids.
- Added deterministic cluster id generation and dedupe-key fallback.
- Added dedupe-key merge behavior for existing clusters.
- Added early-signal to official-confirmation metadata links.
- Added conflict metadata preservation.
- Added a marked temporary `bootstrap_clusterer_evaluation` path when no Evaluator task exists.
- Avoided clusterer/harness circular imports with lazy imports for harness-only types.
- Added Clusterer materialization tests and a full AgentScope Scout-to-Clusterer closed-loop test.

Why:

- Phase 8 still relied on Scout-side bootstrap cluster creation when no real Clusterer existed.
- Connor.ai needs event-level dedupe and canonical claims before the Evaluator group can make meaningful decisions.
- The Clusterer should be an AgentScope role, but cluster persistence must remain a Connor harness responsibility.
- Historical logic chains require explicit links between earlier signals and later confirmations.

Files changed:

- `app/agents/__init__.py`
- `app/agents/outputs.py`
- `app/agents/registry.py`
- `app/clusterer/__init__.py`
- `app/clusterer/materialization.py`
- `app/clusterer/tasks.py`
- `app/harness/collect.py`
- `app/harness/config.py`
- `tests/agents/test_registry.py`
- `tests/clusterer/__init__.py`
- `tests/clusterer/test_materialization.py`
- `tests/harness/test_clusterer_closed_loop.py`
- `docs/MASTER_PLAN.md`
- `docs/PROGRESS.md`
- `docs/plans/phase-09-clusterer.md`
- `docs/adr/0011-clusterer-materialization-boundary.md`
- `docs/DEV_LOG.md`

Checks:

- `python -m pytest tests\clusterer tests\harness\test_clusterer_closed_loop.py tests\agents\test_registry.py -q`: 5 passed.
- `python -m pytest -q`: 56 passed.
- `python -m compileall app tests`: passed.

Effect:

- Phase 9 is complete.
- Scout outputs now become candidates, and Clusterer outputs now become real `EventCluster` records.
- Clusters preserve canonical claims, candidate lineage, evidence lineage, timeline entries, conflicts, and confirmation links.
- The collect loop can run through Scout -> Clusterer -> temporary evaluation -> gate without relying on Scout-side cluster bootstrap.

Open follow-ups:

- Start Phase 10: Evaluator Group.
- Replace `bootstrap_clusterer_evaluation` with Frontier/Event/Market evaluator materialization.
- Add structured evaluator scoring rules for early signals, confirmed events, and tech-finance clusters.

## 2026-07-04

### Infrastructure Review Fixes: Watchlist, Harness Errors, Full State, Clusterer Boundary, IDs

What we did:

- Reviewed six externally flagged issues against the current codebase.
- Confirmed and fixed the `WatchlistRepository.list_active_due()` comparison direction.
- Replaced hard-coded watchlist status strings with `WatchStatus` enum values.
- Changed `DailyRunHarness.run()` so unexpected exceptions are no longer swallowed.
- Ensured both `HarnessError` and non-`HarnessError` failures persist FAILED run state before re-raising.
- Added full traceback storage in failed run trace events through `HarnessContext.fail_run(error_detail=...)`.
- Made `DailyRunHarness.resume()` refuse direct resume from `FAILED` state.
- Reduced `RunRepository.get_full_state()` query fanout by loading run-scoped child payloads through one `UNION ALL` query and loading thread statuses with one `IN` query.
- Added `app/exceptions.py` and kept `app/harness/exceptions.py` as a compatibility re-export.
- Replaced Clusterer materializer's `context: Any` with a `ClusterMaterializationContext` Protocol.
- Removed Clusterer materializer's delayed harness exception import.
- Added `app/core/ids.py` with `IdPrefix`, `deterministic_id()`, and `random_id()`.
- Migrated runtime ID generation in tracing, artifacts, tool evidence, daily run ids, Scout materialization, and Clusterer materialization to the centralized ID helpers.
- Added a workspace-local `tmp_path` fixture so tests run under the current restricted Windows sandbox.

Why:

- Phase 11 watchlist cleanup would be incorrect if due items were queried as `watch_until >= before`.
- Silent unexpected exceptions would make production debugging and tests dangerously misleading.
- FAILED resume semantics needed to be explicit before adding manual recovery flows.
- Full run reconstruction is on the future Dashboard hot path and should avoid avoidable query fanout.
- Clusterer should depend on stable core exceptions and an explicit context protocol, not a harness import cycle and `Any`.
- ID generation should be consistent and provide more entropy than scattered 8/16-char truncation.

Files changed:

- `.gitignore`
- `app/core/__init__.py`
- `app/core/ids.py`
- `app/exceptions.py`
- `app/clusterer/materialization.py`
- `app/harness/context.py`
- `app/harness/exceptions.py`
- `app/harness/materialization.py`
- `app/harness/runner.py`
- `app/repositories/domain.py`
- `app/repositories/runs.py`
- `app/services/artifacts.py`
- `app/services/tracing.py`
- `app/tools/executor.py`
- `tests/conftest.py`
- `tests/core/__init__.py`
- `tests/core/test_ids.py`
- `tests/harness/test_daily_run_harness.py`
- `tests/repositories/test_repository_persistence.py`
- `docs/DEV_LOG.md`

Checks:

- `python -m pytest -q`: 62 passed.
- `python -m compileall app tests`: passed.

Effect:

- Watchlist due querying now returns active/reactivated expired items correctly.
- Unexpected harness bugs are visible to callers and preserve traceback in trace records.
- FAILED runs cannot be resumed implicitly.
- Full run reconstruction now uses batched payload loading instead of many independent child repository queries.
- Clusterer materialization has a typed context boundary and no delayed harness exception import.
- Runtime ID generation now goes through one shared helper module.
- Tests are stable in the current workspace-restricted environment.

Open follow-ups:

- Phase 10 should replace `bootstrap_clusterer_evaluation` with real evaluator materialization.
- A later persistence phase can add ORM relationships if Dashboard read paths need richer eager-loading behavior than payload union reconstruction.

### Phase 10 Complete: Evaluator Group

What we did:

- Added `EvaluationDraft` and extended `EvaluatorOutput` so AgentScope evaluator agents can return complete structured evaluation proposals.
- Added the `app/evaluators` package with evaluator profiles, task construction, compact cluster context, and materialization.
- Defined role profiles for Frontier Evaluator, Event Evaluator, and Market Evaluator.
- Wired evaluator profile prompt extensions into the default AgentScope role registry.
- Added `EvaluatorTaskFactory` so evaluator tasks carry a profile and evaluation output contract.
- Added `EvaluatorOutputMaterializer` to validate drafts, create `EvaluationResult` records, mark selected clusters, update run metadata, and write `EVALUATION_CREATED` trace events.
- Connected evaluator materialization and `cluster_context` injection into `CollectLoopHarness`.
- Added a `materialize_evaluator_outputs` harness config flag.
- Added tests for profile validation, task context, materialization, invalid draft rejection, AgentScope closed-loop execution, and registry prompt wiring.
- Added Phase 10 plan documentation and ADR 0012.

Why:

- Phase 9 still used marked `bootstrap_clusterer_evaluation` records when no evaluator task existed.
- Connor.ai needs real evaluator agents before Watchlist, Archive, Intelligence Threads, and report writing can rely on judgment outcomes.
- Early Signals need looser selection standards than Confirmed Events, but both must remain auditable and traceable.
- AgentScope should execute evaluator agents, while Connor should own validation, persistence, trace, and gate integration.

Files changed:

- `app/agents/__init__.py`
- `app/agents/outputs.py`
- `app/agents/registry.py`
- `app/evaluators/__init__.py`
- `app/evaluators/profiles.py`
- `app/evaluators/tasks.py`
- `app/evaluators/materialization.py`
- `app/harness/collect.py`
- `app/harness/config.py`
- `tests/agents/test_registry.py`
- `tests/evaluators/__init__.py`
- `tests/evaluators/test_profiles.py`
- `tests/evaluators/test_materialization.py`
- `tests/harness/test_evaluator_closed_loop.py`
- `docs/MASTER_PLAN.md`
- `docs/PROGRESS.md`
- `docs/plans/phase-10-evaluator-group.md`
- `docs/adr/0012-evaluator-materialization-boundary.md`
- `docs/DEV_LOG.md`

Checks:

- `python -m pytest tests\evaluators tests\harness\test_evaluator_closed_loop.py tests\agents\test_registry.py -q`: 10 passed.
- `python -m pytest -q`: 71 passed.
- `python -m compileall app tests`: passed.

Effect:

- Phase 10 is complete.
- Connor.ai now has a real Frontier/Event/Market Evaluator group path.
- AgentScope evaluator output can become persistent `EvaluationResult` records through a typed Connor materialization boundary.
- The collect gate can enter writing from real evaluator decisions rather than temporary clusterer bootstrap evaluations.
- Frontier evaluation preserves the looser, trackability-first standard for early signals.
- Event and Market evaluation keep stricter requirements for confirmed facts and finance impact chains.

Open follow-ups:

- Start Phase 11: Watchlist + Archive + Intelligence Threads.
- Convert evaluator decisions such as `short_watch`, `followup_later`, `archive`, and selected clusters into cost-aware memory objects.
- Preserve historical logic chains without letting active watchlist size grow without bounds.

### Phase 11 Complete: Watchlist, Archive, and Intelligence Threads

What we did:

- Added structured Watchlist Agent output schemas: `WatchlistDraft`, `ArchiveDraft`, `ThreadTimelineDraft`, `ThreadDraft`, and `WatchlistAgentOutput`.
- Bound `AgentRole.WATCHLIST_AGENT` to `WatchlistAgentOutput`.
- Added a Watchlist Agent prompt extension for TTLs, archive behavior, and intelligence threads.
- Added the `app/watchlist` package with task construction, memory context shaping, materialization, and deterministic lifecycle service.
- Added `WatchlistOutputMaterializer` for creating/updating `WatchlistItem`, `ArchivedSignal`, and `IntelligenceThread` records.
- Added `WatchlistLifecycleService` for due-watch expiration and default evaluator-memory sync.
- Connected watchlist materialization, due expiration, and memory-context injection into `CollectLoopHarness`.
- Added harness config flags for watchlist output materialization, due expiration, and evaluator-memory auto-sync.
- Added trace object mappings for watchlist, archive, and thread records.
- Added centralized ID prefixes for watchlist, archive, and thread objects.
- Added collect-gate metrics for watchlist, archive, and thread counts.
- Added Phase 11 tests and documentation.

Why:

- Evaluator decisions need to become durable memory, not just one-run decisions.
- Watchlist growth must be bounded so long-running operation does not become too expensive.
- Archive should preserve historical signals instead of deleting them.
- Intelligence Threads are the foundation for later logic-chain analysis across days.
- The Watchlist Agent should make memory proposals through AgentScope, while Connor owns persistence, lifecycle, and trace.

Files changed:

- `app/agents/__init__.py`
- `app/agents/outputs.py`
- `app/agents/registry.py`
- `app/core/ids.py`
- `app/harness/collect.py`
- `app/harness/config.py`
- `app/harness/gates.py`
- `app/services/tracing.py`
- `app/watchlist/__init__.py`
- `app/watchlist/tasks.py`
- `app/watchlist/materialization.py`
- `app/watchlist/lifecycle.py`
- `tests/agents/test_registry.py`
- `tests/watchlist/__init__.py`
- `tests/watchlist/test_materialization.py`
- `tests/watchlist/test_lifecycle.py`
- `tests/harness/test_watchlist_closed_loop.py`
- `docs/MASTER_PLAN.md`
- `docs/PROGRESS.md`
- `docs/plans/phase-11-watchlist-archive-threads.md`
- `docs/adr/0013-watchlist-lifecycle-boundary.md`
- `docs/DEV_LOG.md`

Checks:

- `python -m pytest tests\watchlist tests\harness\test_watchlist_closed_loop.py tests\agents\test_registry.py -q`: 6 passed.
- `python -m pytest -q`: 76 passed.
- `python -m compileall app tests`: passed.

Effect:

- Phase 11 is complete.
- Connor.ai now has an AgentScope Watchlist Agent path for watchlist/archive/thread proposals.
- Connor can create active watch items, archive stale or low-value signals, and maintain intelligence thread timelines.
- Due watch items can expire automatically into archives.
- When no Watchlist Agent task is scheduled, evaluator decisions can still create conservative default memory.
- Watchlist, archive, and thread updates are now visible in trace timelines.

Open follow-ups:

- Start Phase 12: Writing Loop.
- Materialize Writer, Reviewer, and Editor outputs into report and review records.
- Generate `full_markdown`, `full_json`, `evidence_map`, `watchlist_updates`, and `trace_timeline`.
- Ensure Reviewer blocks reports that write early signals as confirmed facts.

### Post-Phase 11 Review Fixes: Harness, Timeout, Trace, Artifact, and Watchlist Hardening

What we did:

- Reviewed the second-round bugfix diff and fixed the remaining issues.
- Changed trace sequence assignment so the per-run lock covers sequence lookup, trace event creation, repository add, and flush.
- Moved trace sequence locking to class-level per-run locks so separate `TraceService` instances in the same process share the same lock.
- Added explicit `asyncio.TimeoutError` handling in `AgentRunner` with non-empty error messages and timeout metadata.
- Added non-empty fallback error summaries for empty-message exceptions in both `AgentRunner` and `DailyRunHarness`.
- Fixed Watchlist lifecycle archive dedupe to use `ArchivedSignal.original_cluster_id` instead of metadata.
- Added regression tests for timeout errors, empty-message failures, trace flush/sequence locking, artifact orphan cleanup, archive cluster fallback dedupe, and thread timeline event-time preservation.

Why:

- The earlier trace TOCTOU fix only locked `max(seq)+1`, not insertion.
- Timeout exceptions can stringify to an empty string, which can break failed-run validation and hide the real error.
- Some third-party/runtime exceptions can also stringify to an empty string, so generic exception handling needs the same fallback.
- Archive dedupe should use the domain lineage field, not optional metadata.
- The new hardening should be directly tested rather than relying only on existing broad tests.

Files changed:

- `app/agents/runner.py`
- `app/services/tracing.py`
- `app/watchlist/lifecycle.py`
- `tests/agents/test_runner.py`
- `tests/services/test_tracing.py`
- `tests/services/test_artifacts.py`
- `tests/watchlist/test_lifecycle.py`
- `tests/watchlist/test_materialization.py`
- `docs/DEV_LOG.md`

Checks:

- `python -m pytest tests\agents\test_runner.py tests\harness\test_daily_run_harness.py -q`: 9 passed.
- `python -m pytest tests\agents\test_runner.py tests\services\test_tracing.py tests\services\test_artifacts.py tests\watchlist -q`: 20 passed.
- `python -m pytest -q`: 83 passed.
- `python -m compileall app tests`: passed.
- `git diff --check`: passed.

Effect:

- Agent timeout failures now produce usable trace errors and non-empty raised exceptions.
- Empty-message runtime failures now persist FAILED run/trace state instead of masking the original error.
- Trace sequence allocation is safer within one process and across multiple `TraceService` instances.
- Archive dedupe no longer depends on optional metadata.
- Artifact cleanup and watchlist/thread hardening now have direct regression coverage.

Open follow-ups:

- A future database migration should add a unique constraint on `(run_id, seq)` plus retry for full multi-process trace sequence safety.

### Phase 12: Writing Loop

What we did:

- Added structured writing drafts for Writer, Reviewer, and Editor outputs.
- Added `app/writing` with `WritingOutputMaterializer` and `WritingTaskFactory`.
- Integrated writing output materialization into `WritingLoopHarness`.
- Added `materialize_writing_outputs` harness config.
- Added report/review/issue ID prefixes to centralized ID generation.
- Materialized Writer drafts into `DailyReport` records with generated markdown, JSON, evidence maps, watchlist updates, and trace timeline IDs.
- Materialized Reviewer drafts into `ReviewResult` and `ReviewIssue` records.
- Materialized Editor revised report drafts back into `DailyReport`.
- Added a deterministic Reviewer guard that blocks early signals written with confirmed-fact language.
- Added task contexts so Writer sees selected intelligence, Reviewer sees report/evidence/trace context, and Editor sees report plus latest review issues.
- Added a writing loop test where the agent runner performs no repository writes; Connor materializes every writing artifact itself.
- Added Phase 12 plan and ADR 0014.

Why:

- Writing agents should produce structured drafts, not directly mutate persistence.
- Final reports need the same replayable evidence and trace boundary as collection, clustering, evaluation, and watchlist memory.
- Markdown and dashboard JSON should come from the same structured report sections.
- Reviewer must have deterministic backup protection against presenting early signals as confirmed facts.

Files changed:

- `app/agents/outputs.py`
- `app/agents/__init__.py`
- `app/agents/prompts.py`
- `app/core/ids.py`
- `app/harness/config.py`
- `app/harness/writing.py`
- `app/writing/__init__.py`
- `app/writing/materialization.py`
- `app/writing/tasks.py`
- `tests/writing/__init__.py`
- `tests/writing/test_materialization.py`
- `tests/harness/test_writing_loop.py`
- `docs/PROGRESS.md`
- `docs/plans/phase-12-writing-loop.md`
- `docs/adr/0014-writing-materialization-boundary.md`
- `docs/DEV_LOG.md`

Checks:

- `python -m pytest tests\writing\test_materialization.py tests\harness\test_writing_loop.py -q`: 6 passed.
- `python -m pytest -q`: 88 passed.
- `python -m compileall app tests`: passed.
- `git diff --check`: passed.

Effect:

- Connor.ai can now run `Writer -> Reviewer -> Editor -> Reviewer -> Final Report` without agent-side repository writes.
- `DailyReport` now receives generated `full_markdown`, `full_json`, `evidence_map`, `watchlist_updates`, and `trace_timeline_ids`.
- `ReviewResult` and `ReviewIssue` are first-class outputs of Reviewer materialization.
- Early-signal uncertainty has a deterministic quality guard in addition to agent review.

Open follow-ups:

- Start Phase 13: FastAPI and Dashboard Contract.
- Expose run, report, trace, cluster, watchlist, and thread endpoints.
- Add dashboard-facing schemas over the structured daily report payload.

### Phase 13: FastAPI and Dashboard Contract

What we did:

- Added FastAPI and uvicorn to project dependencies.
- Added `app/api` package with app factory, dependencies, routes, and public response schemas.
- Added ASGI entrypoint at `app/main.py`.
- Implemented `POST /runs/daily`.
- Implemented `GET /runs/{run_id}`.
- Implemented `GET /runs/{run_id}/trace`.
- Implemented `GET /runs/{run_id}/clusters`.
- Implemented `GET /reports/{report_id}`.
- Implemented `GET /watchlist`.
- Implemented `GET /threads`.
- Implemented `GET /threads/{thread_id}`.
- Added explicit duplicate-run conflict handling for `POST /runs/daily`.
- Added repository helpers for dashboard list endpoints.
- Added API tests with a thread-safe SQLite StaticPool setup for FastAPI TestClient.
- Added Phase 13 plan and ADR 0015.

Why:

- The Next.js Dashboard needs a stable backend contract before frontend work.
- API endpoints should expose persisted, traceable Connor state without owning agent loop execution.
- Scheduled run creation is safe through the harness, while full execution should wait for worker/queue boundaries.
- Dashboard reads should go through repositories/services, not raw ORM row access.

Files changed:

- `pyproject.toml`
- `app/api/__init__.py`
- `app/api/dependencies.py`
- `app/api/main.py`
- `app/api/routes.py`
- `app/api/schemas.py`
- `app/main.py`
- `app/repositories/base.py`
- `app/repositories/domain.py`
- `tests/api/__init__.py`
- `tests/api/test_routes.py`
- `docs/PROGRESS.md`
- `docs/plans/phase-13-fastapi-dashboard-contract.md`
- `docs/adr/0015-fastapi-dashboard-boundary.md`
- `docs/DEV_LOG.md`

Checks:

- `python -m pytest tests\api\test_routes.py -q`: 3 passed.
- `python -m pytest -q`: 91 passed.
- `python -m compileall app tests`: passed.
- `git diff --check`: passed.

Effect:

- Connor.ai now has a FastAPI contract for runs, reports, trace, clusters, watchlist, and threads.
- Dashboard responses expose `full_markdown`, `full_json`, `evidence_map`, `watchlist_updates`, and trace IDs from persisted reports.
- API creation/read behavior is covered by HTTP-level tests.

Open follow-ups:

- Start Phase 14: real source expansion, beginning with GitHub / Hugging Face.

### Phase 14: Source Expansion, GitHub and Hugging Face Tools

What we did:

- Added optional source credentials and user-agent configuration.
- Added a small JSON HTTP helper for public source tools.
- Added GitHub repository search and code search tools.
- Added Hugging Face model and dataset search tools.
- Registered the tools in the default `ToolRegistry` with role permissions and timeout defaults.
- Exported the source tools from `app.tools`.
- Updated `ToolExecutor` so `ToolSpec.timeout_seconds` becomes an effective execution-context default.
- Added tests that normalize fake GitHub and Hugging Face responses into `ToolEnvelopeItem` records.
- Added an executor test proving source tool output creates evidence and trace records.
- Added Phase 14 plan and ADR 0016.

Why:

- Connor.ai needs real source collection, but every source result must still pass through the existing evidence and trace boundary.
- GitHub and Hugging Face are the first source group because they are structured, public, and directly relevant to Code & Model Scout and Research Scout work.
- Source adapters should not own persistence, artifacts, or trace construction.

Files changed:

- `README.md`
- `app/config.py`
- `app/tools/__init__.py`
- `app/tools/builtin.py`
- `app/tools/executor.py`
- `app/tools/http.py`
- `app/tools/source_tools.py`
- `tests/tools/test_source_tools.py`
- `docs/MASTER_PLAN.md`
- `docs/PROGRESS.md`
- `docs/plans/phase-14-source-expansion.md`
- `docs/adr/0016-public-source-tool-boundary.md`
- `docs/DEV_LOG.md`

Checks:

- `python -m pytest tests\tools\test_source_tools.py -q`: 10 passed.
- `python -m pytest tests\tools tests\agents\test_registry.py tests\agents\test_runner.py -q`: 24 passed.
- `python -m pytest tests\watchlist\test_lifecycle.py tests\harness\test_quality_gates.py -q`: 8 passed.
- `python -m pytest -q`: 104 passed.
- `python -m compileall app tests`: passed.
- `git diff --check`: passed.

Effect:

- AgentScope agents can now call real GitHub and Hugging Face source tools through Connor's `FunctionTool -> ToolExecutor -> ToolEnvelope -> EvidenceItem -> TraceEvent` path.
- Expected HTTP failures become structured tool errors instead of untraceable missing data.
- Source tool tests do not depend on live network access.

Open follow-ups:

- Continue Phase 14 with arXiv and OpenReview.
- Add official blog/API changelog source tools.
- Add SEC/IR/earnings sources after finance-source boundaries are explicit.

### Post-Review Bugfixes: Source Tools, Watchlist Lifecycle, Trace Locks, and Followup Gates

What we did:

- Fixed watchlist TTL expiration so a current maintenance run can expire due active/reactivated watch items from previous runs.
- Preserved watch/archive ownership by grouping due watch items by their original `run_id` and materializing archives against that owner run.
- Removed unsafe per-run trace lock deletion at the end of `DailyRunHarness.run()`.
- Changed AgentScope Connor tools to `is_concurrency_safe=False` because they share a SQLAlchemy session and write trace/evidence/artifact records.
- Treated `timeout_seconds=None` as missing so `ToolSpec.timeout_seconds` is still injected.
- Added GitHub `items` payload shape validation so malformed source responses become structured `unexpected_payload` errors.
- Completed followup-budget semantics so targeted followup can still run when collect rounds are exhausted but followup budget remains.
- Added regression tests for cross-run watch expiration, null timeout defaulting, GitHub malformed `items`, sequential AgentScope tools, and followup-at-collect-limit behavior.

Why:

- Long-running Connor.ai deployments must not let historical watchlist items remain active forever.
- Trace sequence protection should not be invalidated by deleting a lock while another same-run execution may still be active.
- Real source tools must have bounded network calls even when an agent passes malformed params.
- AgentScope concurrency metadata must match Connor's database side effects.
- Followup rounds were documented as independent from collect rounds, but the gate still enforced collect budget.

Files changed:

- `app/agents/agentscope_tools.py`
- `app/harness/collect.py`
- `app/harness/gates.py`
- `app/harness/runner.py`
- `app/services/tracing.py`
- `app/tools/executor.py`
- `app/tools/source_tools.py`
- `app/watchlist/lifecycle.py`
- `tests/agents/test_registry.py`
- `tests/harness/test_quality_gates.py`
- `tests/tools/test_source_tools.py`
- `tests/watchlist/test_lifecycle.py`
- `docs/PROGRESS.md`
- `docs/plans/phase-14-source-expansion.md`
- `docs/DEV_LOG.md`

Checks:

- `python -m pytest tests\watchlist\test_lifecycle.py -q`: 4 passed.
- `python -m pytest tests\tools\test_source_tools.py tests\tools\test_executor.py -q`: 14 passed.
- `python -m pytest tests\agents\test_registry.py tests\agents\test_runner.py -q`: 7 passed.
- `python -m pytest tests\harness -q`: 18 passed.
- `python -m pytest tests\tools tests\agents\test_registry.py tests\agents\test_runner.py -q`: 24 passed.
- `python -m pytest tests\watchlist\test_lifecycle.py tests\harness\test_quality_gates.py -q`: 8 passed.
- `python -m pytest -q`: 104 passed.
- `python -m compileall app tests`: passed.
- `git diff --check`: passed.

Effect:

- Active watchlist cleanup now works across historical runs.
- Trace lock protection remains stable for a run within the process lifetime.
- Source tool timeout and malformed-payload behavior is safer.
- AgentScope will schedule Connor tools sequentially.
- Followup loops now match the intended independent-budget model.

Open follow-ups:

- Add a database-level `(run_id, seq)` uniqueness constraint and retry loop for multi-process trace safety.
- Consider a dedicated maintenance trace event on the current run when it expires watch items owned by previous runs.

### Phase 14: arXiv and OpenReview Source Tools

What we did:

- Added text-response support to the shared public-source HTTP helper.
- Added `arxiv_search` as a registered source tool that calls the arXiv API, parses Atom XML, and normalizes papers into `ToolEnvelopeItem` records.
- Added `openreview_note_search` as a registered source tool that calls the OpenReview API 2 `/notes` endpoint with bounded note filters.
- Registered both tools for Orchestrator, Code & Model Scout, and Research Scout through the default `ToolRegistry`.
- Exported the tools from `app.tools`.
- Added fake-client tests for arXiv Atom normalization, OpenReview note normalization, malformed arXiv XML handling, and default registry exposure.
- Updated the Phase 14 source-expansion plan and progress tracker.

Why:

- Connor.ai needs research-source signals to sit behind the same audited tool, evidence, artifact, and trace path as code/model signals.
- arXiv and OpenReview are structured enough to add now without weakening the source boundary.
- OpenReview anonymous live access can return a challenge response, so the tool records that as a structured source failure instead of trying to bypass access controls.

Files changed:

- `app/tools/http.py`
- `app/tools/source_tools.py`
- `app/tools/builtin.py`
- `app/tools/__init__.py`
- `tests/tools/test_source_tools.py`
- `docs/PROGRESS.md`
- `docs/plans/phase-14-source-expansion.md`
- `docs/DEV_LOG.md`

Checks:

- `python -m pytest tests\tools\test_source_tools.py -q`: 14 passed.
- `python -m pytest tests\tools tests\agents\test_registry.py tests\agents\test_runner.py -q`: 28 passed.
- `python -m pytest -q`: 108 passed.
- `python -m compileall app tests`: passed.
- `git diff --check`: passed.

Effect:

- Research Scout can now collect arXiv and OpenReview research evidence through Connor's existing `FunctionTool -> ToolExecutor -> ToolEnvelope -> EvidenceItem -> TraceEvent` path.
- Malformed XML and source access errors remain traceable tool outcomes instead of unstructured exceptions.

Open follow-ups:

- Add official blog/API changelog source tools.
- Decide whether OpenReview authenticated access belongs in Phase 14 or a later credential-management phase.

### Phase 14: Official Feed and API Changelog Source Tools

What we did:

- Added `official_feed_search` for curated official RSS/Atom blog feeds.
- Added `api_changelog_search` for curated official API changelog feeds/pages.
- Registered both tools for Orchestrator and Official Scout through the default `ToolRegistry`.
- Kept source selection on audited `source_key` / `source_keys` values rather than arbitrary URLs.
- Added RSS and Atom feed normalization into `ToolEnvelopeItem`.
- Added HTML changelog page parsing into heading-section evidence for sources without stable feeds.
- Added HTML snippet cleanup so evidence snippets do not retain raw markup.
- Added regression tests for RSS normalization, HTML changelog normalization, unknown source keys, malformed XML, and Official Scout registry exposure.
- Updated Phase 14 plan, progress tracker, master plan, and ADR 0016.

Why:

- Confirmed first-party updates are a different trust category from code/model/research signals and should be available to Official Scout with official evidence strength.
- Agent freedom should happen inside an audited source catalog, not through arbitrary URL fetching.
- Some official API changelogs are pages rather than feeds, so the source layer needs a conservative page-section fallback while preserving traceability.

Files changed:

- `app/tools/source_tools.py`
- `app/tools/builtin.py`
- `app/tools/__init__.py`
- `tests/tools/test_source_tools.py`
- `docs/PROGRESS.md`
- `docs/MASTER_PLAN.md`
- `docs/plans/phase-14-source-expansion.md`
- `docs/adr/0016-public-source-tool-boundary.md`
- `docs/DEV_LOG.md`

Checks:

- `python -m pytest tests\tools\test_source_tools.py -q`: 19 passed.
- `python -m pytest tests\tools tests\agents\test_registry.py tests\agents\test_runner.py -q`: 33 passed.
- `python -m pytest tests\scouts\test_profiles.py tests\harness\test_all_scouts_closed_loop.py -q`: 6 passed.
- `python -m pytest -q`: 113 passed.
- `python -m compileall app tests`: passed.
- `git diff --check`: passed.

Effect:

- Official Scout can now collect first-party blog and API changelog evidence through Connor's existing `FunctionTool -> ToolExecutor -> ToolEnvelope -> EvidenceItem -> TraceEvent` path.
- Official-source tools return available catalog keys in metadata so agents can choose sources without being able to fetch arbitrary URLs.
- Malformed official feeds and unknown source keys become traceable `ToolError` entries.

Open follow-ups:

- SEC / IR / earnings-source tools are completed in the following log section.
- Consider moving source catalogs into database/config once Dashboard source management exists.

### Phase 14: SEC and Investor Relations Source Tools

What we did:

- Added `CONNOR_SEC_USER_AGENT` so SEC requests can use a dedicated fair-access User-Agent.
- Added `sec_company_filings` for recent SEC EDGAR submissions by ticker or CIK.
- Added `sec_company_facts` for selected SEC XBRL company facts by ticker or CIK.
- Added `investor_relations_search` for curated company investor-relations pages.
- Resolved tickers through SEC's official `company_tickers.json` map instead of a local hardcoded mapping.
- Normalized SEC filing rows into `ToolEnvelopeItem` records with CIK, ticker, form, accession number, filing date, and archive URL metadata.
- Normalized SEC XBRL fact rows into `ToolEnvelopeItem` records with taxonomy, concept, unit, value, filing, and accession lineage.
- Registered the finance tools for Orchestrator and Finance Scout through the default `ToolRegistry`.
- Exported the finance tools from `app.tools`.
- Added fake-client tests for SEC filing normalization, SEC company-fact normalization, missing identifier errors, investor-relations page normalization, and Finance Scout registry exposure.
- Updated README, Phase 14 plan, progress tracker, master plan, and ADR 0016.

Why:

- Tech-Finance intelligence needs first-party and regulator-grade evidence for revenue, capex, guidance, filings, and supply-chain implications.
- SEC EDGAR JSON APIs provide high-trust public data without introducing paid-provider dependencies.
- Investor-relations pages should remain inside a curated catalog so Finance Scout can explore company sources without arbitrary web fetching.

Files changed:

- `README.md`
- `app/config.py`
- `app/tools/source_tools.py`
- `app/tools/builtin.py`
- `app/tools/__init__.py`
- `tests/tools/test_source_tools.py`
- `docs/PROGRESS.md`
- `docs/MASTER_PLAN.md`
- `docs/plans/phase-14-source-expansion.md`
- `docs/adr/0016-public-source-tool-boundary.md`
- `docs/DEV_LOG.md`

Checks:

- `python -m pytest tests\tools\test_source_tools.py -q`: 24 passed.
- `python -m pytest tests\tools tests\agents\test_registry.py tests\agents\test_runner.py -q`: 38 passed.
- `python -m pytest tests\scouts\test_profiles.py tests\harness\test_all_scouts_closed_loop.py -q`: 6 passed.
- `python -m pytest -q`: 118 passed.
- `python -m compileall app tests`: passed.
- `git diff --check`: passed.
- Live smoke: `sec_company_filings` and `sec_company_facts` returned current NVDA items from SEC endpoints.

Effect:

- Finance Scout can now collect SEC filings, SEC XBRL facts, and curated IR page evidence through Connor's existing `FunctionTool -> ToolExecutor -> ToolEnvelope -> EvidenceItem -> TraceEvent` path.
- SEC evidence carries accession lineage that later evaluators and reports can connect back to EDGAR archive URLs.
- Missing ticker/CIK, malformed SEC payloads, and source HTTP failures become traceable `ToolError` entries.

Open follow-ups:

- Hacker News is completed in the following log section; Reddit/X social sources still require explicit auth, rate-limit, and content-policy boundaries.
- Consider moving source catalogs into database/config once Dashboard source management exists.

### Phase 14: Hacker News Community Source Tool

What we did:

- Added `hacker_news_feed_search` for bounded Hacker News official API feed collection.
- Registered the tool for Orchestrator and Social Scout through the default `ToolRegistry`.
- Exported the tool from `app.tools`.
- Implemented bounded feed selection, bounded item fetching, local query matching, and normalized HN item evidence.
- Preserved HN thread URL, external URL, score, comment count, author, item id, item type, and feed metadata.
- Added fake-client tests for matching item normalization, unknown feed fallback, malformed feed payloads, and Social Scout registry exposure.
- Updated Phase 14 plan, progress tracker, master plan, and ADR 0016.

Why:

- Hacker News is a high-signal community source for early AI/model/tooling discussions and has an official public Firebase API.
- The tool should not depend on third-party search APIs or arbitrary web fetching.
- Reddit, X/Twitter, and other authenticated social sources need explicit credentials, rate-limit, platform-policy, and content-boundary handling before implementation.

Files changed:

- `app/tools/source_tools.py`
- `app/tools/builtin.py`
- `app/tools/__init__.py`
- `tests/tools/test_source_tools.py`
- `docs/PROGRESS.md`
- `docs/MASTER_PLAN.md`
- `docs/plans/phase-14-source-expansion.md`
- `docs/adr/0016-public-source-tool-boundary.md`
- `docs/DEV_LOG.md`

Checks:

- `python -m pytest tests\tools\test_source_tools.py -q`: 28 passed.
- `python -m pytest tests\tools tests\agents\test_registry.py tests\agents\test_runner.py -q`: 42 passed.
- `python -m pytest tests\scouts\test_profiles.py tests\harness\test_all_scouts_closed_loop.py -q`: 6 passed.
- `python -m pytest -q`: 122 passed.
- `python -m compileall app tests`: passed.
- `git diff --check`: passed.
- Live smoke: `hacker_news_feed_search` returned current AI-related Hacker News items.

Effect:

- Social Scout can now collect bounded Hacker News community evidence through Connor's existing `FunctionTool -> ToolExecutor -> ToolEnvelope -> EvidenceItem -> TraceEvent` path.
- Community-source collection remains traceable, bounded, and policy-conscious.

Open follow-ups:

- Add Reddit/X/Twitter only after auth, rate-limit, platform-policy, and content boundaries are explicit.
- Consider a dedicated HN item/thread lookup tool if follow-up workflows need comment-level evidence.
