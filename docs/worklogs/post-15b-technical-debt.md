# Worklog: Post-15B Technical Debt

Date: 2026-07-06

Status: In progress

## Part 1: AgentScope Tool Offload

### Used

- `app/agents/agentscope_tools.py`
- `app/agents/runner.py`
- AgentScope `FunctionTool` implementation inspection
- Agent registry and runner tests
- Full non-smoke test suite

### Did

- Fixed the remaining medium-priority AgentScope tool bridge issue where synchronous Connor tool execution could block the async ReAct loop.
- Converted Connor tools exposed to AgentScope from sync callables into async callables.
- Offloaded synchronous `ToolExecutor.execute()` work into a per-bridge single-thread executor.
- Added thread-safe snapshots for executed tool results and evidence IDs.
- Ensured `AgentRunner.run_async()` closes the bridge worker after success, fallback, timeout, or failure.
- Updated the shared SQLite in-memory test fixture to support cross-thread tool execution with `StaticPool` and `check_same_thread=False`.
- Added a regression test proving a slow synchronous tool no longer blocks the event loop.

### How

- `AgentScopeToolBridge._create_connor_tool()` now returns `async def connor_tool(...)`.
- Tool calls run through `loop.run_in_executor(...)` using one worker thread per bridge, preserving the existing sequential database side-effect boundary.
- The bridge keeps `is_concurrency_safe=False`, so AgentScope still treats Connor tools as non-concurrent.
- `executed_results_snapshot()` and `executed_result_count()` replace direct reads of the mutable result list from the runner.
- The runner awaits `bridge.aclose()` in a `finally` block.

### Problems and Solutions

- Problem: Simply using `asyncio.to_thread()` could send different tool calls to different worker threads and make shared SQLAlchemy session usage harder to reason about.
  - Solution: Use a dedicated single-thread executor per bridge.
- Problem: The previous in-memory SQLite fixture was not safe for threaded tool execution.
  - Solution: Use `StaticPool` and `check_same_thread=False` in the test fixture.
- Problem: A ruff pass found an unrelated missing `EventCluster` import in writing materialization.
  - Solution: Added the missing import while preserving the existing Phase 15B logic.

### Checks

- `python -m ruff check app\agents\agentscope_tools.py app\agents\runner.py tests\agents\test_registry.py tests\conftest.py`: passed.
- `python -m pytest tests\agents -q`: 19 passed.
- `python -m pytest -q --ignore=tests\smoke`: 183 passed.
- `python -m ruff check .`: passed.
- `python -m pytest tests\agents tests\writing -q`: 42 passed.

### Remaining

- Re-run a full non-smoke suite after the next technical-debt batch.
- Decide whether Phase 16 should first clean low-priority source-tool edge cases or move directly into scheduler/Docker work.

## Part 2: Formal Run Startup FK Fix and Report Quality Review

### Used

- Strict live full-cycle smoke test.
- Temporary SQLite database `test_tmp/quality_review_run.db`.
- Persisted final report, clusters, evidence, evaluations, and reviews.

### Did

- Ran a formal daily cycle after committing the Phase 15A/15B checkpoint.
- Found that the run failed before collection when SQLite foreign keys were enabled.
- Fixed the run creation order so `RunRecord` is flushed before the first trace payload artifact is written.
- Re-ran the formal daily cycle successfully.
- Inspected the generated report as a product artifact and listed business-quality issues for the next tuning pass.

### How

- Added an explicit `session.flush()` immediately after `self.context.runs.add(run)` in `DailyRunHarness.create_run()`.
- Re-ran harness/service/repository tests to confirm the normal fixture path remained stable.
- Re-ran `tests/smoke/test_full_daily_cycle.py` with `CONNOR_DATABASE_URL=sqlite:///./test_tmp/quality_review_run.db`.
- Queried `daily_reports`, `event_clusters`, `evidence_items`, `evaluation_results`, and `review_results` directly from SQLite.

### Problems and Solutions

- Problem: `TraceService.record_event()` stores trace input/output payloads as artifacts before creating the trace event. With artifact `run_id` foreign keys enabled, the first RUN_STARTED trace artifact failed if the parent run had not been flushed.
  - Solution: Flush the run before recording RUN_STARTED.
- Problem: Enabling foreign keys globally in the shared unit-test fixture exposed many fixture-order assumptions unrelated to the formal run bug.
  - Solution: Keep the generic fixture focused on unit isolation and use the formal smoke path to validate production SQLite foreign-key behavior.

### Checks

- `python -m pytest tests\harness tests\services tests\repositories -q`: 46 passed.
- `python -m ruff check app\harness\runner.py tests\conftest.py`: passed.
- `python -m pytest tests\smoke\test_full_daily_cycle.py -v -s`: 1 passed in 267.39 seconds.

### Report Quality Findings

- The report finalized and had the required structure, but the business quality is still uneven.
- Strongest current output: deterministic structure, clear uncertainty labels, evidence lineage, and concrete watchlist entries.
- Main weaknesses: weak early-signal selection, generic product/preprint uncertainty language, Tech-Finance still stopping at SEC filing metadata, mixed official-update clustering, internal IDs leaking into human markdown, and no inline source links.
