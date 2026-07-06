# Phase 15A Plan: Report Quality and Selection Hardening

Status: Complete

Started: 2026-07-05

## Goal

Move Connor.ai from "can produce a report artifact" to "can produce a business-usable daily intelligence report."

The quality review of a live run showed that the system could collect, cluster, evaluate, write, and review, but the final business output was not yet stable enough:

- The run paused in review instead of finalizing.
- The report over-focused on one research cluster.
- Confirmed official events and Tech-Finance material were collected but disappeared from the report.
- The smoke test accepted a needs-revision report as passing.

Phase 15A hardens the deterministic harness layer so selected material covers the Connor.ai product surface before Worker, queue, or Dashboard work begins.

## Decisions

- Treat `selected_cluster_ids` as a hard writing contract: every selected cluster must appear in at least one report item.
- Separate "writeable with caveat" from "fully confirmed." A follow-up decision can still enter writing if the cluster has enough evidence to be useful in a caveated section.
- Enforce required report bucket coverage at the harness gate, not only through prompts.
- Make smoke tests fail unless the run is actually finalized and the report is final.

## Report Buckets

Connor.ai writes into three core business buckets:

- `early_signals`: `early_signal`, `research`, `code_model`
- `confirmed_events`: `confirmed_event`, `official_update`
- `tech_finance`: `tech_finance`

The collect gate now adds one writeable cluster from any missing required bucket when that bucket is available in the run state.

## Implementation Slices

### Slice 1: Selection Coverage

- Add deterministic report bucket mapping in `QualityGateService`.
- Keep explicit evaluator selections.
- Add writeable follow-up official and finance clusters when their buckets would otherwise be missing.
- Mark all selected clusters as selected when entering writing.

### Slice 2: Writer Contract

- Add `report_quality_contract` to `WritingTaskFactory.writer_context`.
- Include each selected cluster's `report_bucket`, `write_policy`, `required_followups`, and `missing_evidence`.
- Tell Writer that selected clusters must be written with caveats rather than dropped.

### Slice 3: Finalization Gate

- Block finalization when:
  - `full_markdown` is missing.
  - `evidence_map` is missing.
  - `tomorrow_focus` is missing.
  - a selected cluster is not referenced by any report item.
  - a selected report bucket has no matching report item.

### Slice 4: Tests

- Add unit tests for coverage selection.
- Add unit tests for writer context contract.
- Add writing gate tests for missing selected cluster and missing tomorrow focus.
- Harden live smoke test assertions so a paused/needs-revision run fails.

## Checks So Far

- `python -m pytest tests\harness\test_quality_gates.py tests\writing\test_tasks.py -q`
- `python -m pytest tests\harness tests\writing -q`
- `python -m pytest tests\agents\test_runner.py tests\evaluators\test_materialization.py tests\tools\test_source_tools.py -q`
- `python -m pytest -q --ignore=tests\smoke`
- `python -m ruff check .`: passed.
- `python -m pytest -q --ignore=tests\smoke`: 177 passed.
- `python -m pytest tests\smoke\test_full_daily_cycle.py -v -s`: 1 passed; final run reached `finalized / completed`.

## Open Follow-ups

- Add evidence-level URL deduplication for duplicate HN/feed items.
- Calibrate evaluator decisions into an explicit `write_policy` field in Phase 15B.
- Improve source extraction for finance figures so Tech-Finance sections include more actual numbers.
- Register the `slow` pytest marker and decide whether bounded AgentScope ReAct warnings should be hidden or summarized.
