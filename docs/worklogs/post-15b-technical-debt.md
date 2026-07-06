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
