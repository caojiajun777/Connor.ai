# Phase 6 Plan: Loop Harness

Status: Complete

Completed: 2026-07-03

## Goal

Build Connor.ai's product control layer around AgentScope-first agent execution.

Phase 6 answers:

```text
How does a daily run start?
How do collect and writing loops advance?
Where are loop boundaries enforced?
How do quality gates decide follow-up, revision, finalization, or failure?
How are harness decisions persisted as trace and artifacts?
```

## Delivered Architecture

Added:

```text
app/harness/
  __init__.py
  config.py
  context.py
  decisions.py
  exceptions.py
  gates.py
  collect.py
  writing.py
  runner.py
```

The execution path is:

```text
DailyRunHarness
-> CollectLoopHarness
-> QualityGateService.evaluate_collect
-> WritingLoopHarness
-> QualityGateService.evaluate_writing
-> final report / paused manual review / failed run
```

Agent work still flows through Phase 5:

```text
Harness AgentTask
-> AgentRunner
-> AgentScope Agent
-> AgentScope Toolkit / FunctionTool
-> Connor ToolExecutor / TraceService / repositories
```

## Core Contracts

- `HarnessConfig`: loop limits and quality thresholds.
- `HarnessContext`: shared repositories, trace, artifact, and run update helpers.
- `AgentTask`: one harness assignment to an AgentScope role.
- `CollectGateDecision`: structured collect gate output.
- `WritingGateDecision`: structured writing gate output.
- `DailyRunResult`: final top-level harness result.
- `HarnessError`: explicit harness failure.

## Collect Loop

Implemented phases:

```text
collect_planning
-> scouting
-> clustering
-> evaluating
-> watchlist_update
-> evaluation_gate
```

Supported gate outcomes:

- `enter_writing`
- `followup_now`
- `recluster`
- `continue_collecting`
- `needs_manual_review`
- `fail`

The collect gate checks:

- evidence count
- candidate count
- cluster count
- evaluation count
- selected cluster count
- follow-up query count
- collect round budget
- follow-up round budget

## Writing Loop

Implemented phases:

```text
writing
-> reviewing
-> editing
-> final_review
-> finalized
```

Supported gate outcomes:

- `finalize`
- `review_draft`
- `revise`
- `reopen_collect`
- `needs_manual_review`
- `fail`

The writing gate checks:

- draft report existence
- review existence
- reviewer decision
- revision budget
- reopen-collect budget
- final report requirements

## Tracing and Artifacts

Harness records:

- `RUN_STARTED`
- `PHASE_STARTED`
- `PHASE_COMPLETED`
- `GATE_DECISION`
- `REPORT_FINALIZED`
- `ERROR`

Harness archives:

- collect gate snapshots
- writing gate snapshots
- final report snapshot

Snapshots are stored through `ArtifactService`, not ad hoc files.

## Tests Delivered

Added:

```text
tests/harness/
  __init__.py
  helpers.py
  test_quality_gates.py
  test_collect_loop.py
  test_writing_loop.py
  test_daily_run_harness.py
```

Coverage:

- Collect gate follow-up decision.
- Collect gate manual-review pause when budget is exhausted.
- Writing gate finalization only after reviewer pass.
- Collect loop enters writing from selected evaluation.
- Collect loop writes gate trace and snapshot artifact.
- Writing loop revises, edits, final-reviews, and finalizes.
- DailyRunHarness creates a run, collects, writes, finalizes, and persists final report id.

## Checks Run

- `python -m pytest tests\harness -q`: 7 passed.
- `python -m pytest -q`: 45 passed.
- `python -m compileall app tests`: passed.

## Non-Goals Preserved

- No real external data sources yet.
- No full Scout, Clusterer, Evaluator, Watchlist, Writer, Reviewer, or Editor intelligence yet.
- No FastAPI endpoints yet.
- No Docker Compose yet.

## Follow-up Phase

Phase 7 should make one complete single-agent closed loop reliable inside this harness:

```text
create run
-> assign one scout
-> call one tool
-> create evidence
-> create candidate
-> trace and persist everything
```
