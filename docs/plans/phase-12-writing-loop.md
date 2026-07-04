# Phase 12 Plan: Writing Loop

Status: Complete

Completed: 2026-07-04

## Goal

Turn selected intelligence into a reviewed, traceable daily report:

```text
Selected clusters / evaluations / watchlist memory
-> WriterOutput report drafts
-> DailyReport
-> ReviewerOutput review drafts
-> ReviewResult / ReviewIssue
-> EditorOutput revised report drafts
-> final Reviewer pass
-> Final DailyReport
```

The goal is not to let agents write arbitrary markdown blobs. Writer, Reviewer, and Editor remain AgentScope agents, but Connor owns persistence, evidence lineage, quality gates, artifact-ready JSON, and trace.

## Delivered Architecture

Added:

```text
app/writing/__init__.py
app/writing/materialization.py
app/writing/tasks.py
tests/writing/__init__.py
tests/writing/test_materialization.py
```

Updated:

```text
app/agents/outputs.py
app/agents/__init__.py
app/agents/prompts.py
app/core/ids.py
app/harness/config.py
app/harness/writing.py
tests/harness/test_writing_loop.py
docs/PROGRESS.md
docs/DEV_LOG.md
docs/adr/0014-writing-materialization-boundary.md
```

## Agent Output Extension

Added:

- `ReportItemDraft`
- `ReportSectionDraft`
- `ReportDraft`
- `ReviewIssueDraft`
- `ReviewDraft`

Writer can now return:

```json
{
  "summary": "Writer drafted report.",
  "report_drafts": [
    {
      "sections": [
        {
          "section_id": "early_signals",
          "title": "Early Signals",
          "items": [
            {
              "title": "Possible API surface change",
              "category": "early_signal",
              "status_label": "Unconfirmed gray rollout feedback",
              "core_information": "...",
              "why_it_matters": "...",
              "evidence_ids": ["..."],
              "cluster_ids": ["..."],
              "uncertainty_label": "low confidence, high trackability"
            }
          ]
        }
      ]
    }
  ]
}
```

Reviewer can now return:

```json
{
  "summary": "Reviewer requested revision.",
  "decision": "revise",
  "review_drafts": [
    {
      "decision": "revise",
      "required_changes": ["Clarify early-signal uncertainty."],
      "reasoning_summary": "The report overstates an unconfirmed signal."
    }
  ]
}
```

Editor can now return revised `ReportDraft` records instead of mutating the database directly.

## Materialization Boundary

`WritingOutputMaterializer` is the only component that converts writing-loop agent outputs into persisted report and review objects.

It handles:

- Writer draft to `DailyReport`
- Editor revised draft to updated `DailyReport`
- Reviewer draft to `ReviewResult` and `ReviewIssue`
- automatic `full_markdown` rendering when the agent does not provide markdown
- automatic `full_json` generation from structured sections
- automatic `evidence_map` generation from report items
- automatic `watchlist_updates` generation from linked watchlist items
- automatic `trace_timeline_ids` generation and report-trace backfill
- report/review IDs and run metadata updates
- `REPORT_DRAFTED`, `REVIEW_COMPLETED`, and `REPORT_EDITED` trace events

## Reviewer Guard

Phase 12 adds a deterministic uncertainty guard inside reviewer materialization.

If Reviewer tries to pass a report where an `early_signal` item uses confirmed-fact language, the materializer converts the review to `revise` and creates a blocking review issue.

The guard checks status and core wording independently, so an "unconfirmed" status label cannot hide a core statement like "has launched".

## Harness Integration

`WritingLoopHarness` now:

- injects `writing_context` for Writer tasks
- injects `review_context` for Reviewer tasks
- injects `editor_context` for Editor tasks
- materializes writing outputs after each AgentScope agent result when `materialize_writing_outputs` is enabled

The harness still owns loop boundaries, budgets, quality gates, phase completion, and finalization.

## Tests

Added coverage for:

- Writer draft materialization into `DailyReport`
- markdown/json/evidence map/trace timeline generation
- deterministic reviewer guard against early-signal fact language
- guard behavior when fact language appears in core text despite uncertain status
- Editor revised draft materialization
- full writing loop with an agent runner that performs no repository side effects

## Checks

- `python -m pytest tests\writing\test_materialization.py tests\harness\test_writing_loop.py -q`: 6 passed.
- `python -m pytest -q`: 88 passed.
- `python -m compileall app tests`: passed.
- `git diff --check`: passed.

## Effect

Connor.ai can now run the writing side of the topology as a real AgentScope-first loop:

```text
Writer -> Reviewer -> Editor -> Reviewer -> Final Report
```

The final report has the required dashboard-ready surfaces:

- `full_markdown`
- `full_json`
- `evidence_map`
- `watchlist_updates`
- `trace_timeline_ids`

## Open Follow-ups

- Phase 13 should expose reports, trace, watchlist, and run state through FastAPI endpoints.
- Future source-expansion phases should add richer report sections once real source connectors are available.
