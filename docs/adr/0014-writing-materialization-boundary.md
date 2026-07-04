# ADR 0014: Writing Materialization Boundary

Date: 2026-07-04

Status: Accepted

## Context

Phase 12 connects the selected intelligence state to the daily report.

Writer, Reviewer, and Editor are AgentScope agents, but the report is not a free-form text artifact. It must remain:

- evidence-linked
- dashboard-renderable
- reviewable
- replayable through trace
- safe about uncertainty boundaries
- consistent across markdown and JSON

If writing agents directly mutate the database, Connor loses the same reliability properties already established for Scouts, Clusterer, Evaluators, and Watchlist Agent.

## Decision

Use a dedicated `WritingOutputMaterializer`.

Agents return structured drafts:

- `ReportDraft`
- `ReviewDraft`
- `ReviewIssueDraft`

The materializer converts those drafts into:

- `DailyReport`
- `ReviewResult`
- `ReviewIssue`
- trace events
- run metadata updates

`WritingLoopHarness` calls the materializer after each AgentScope result, but it does not own report construction details.

The Reviewer path also includes a deterministic guard: early-signal items cannot pass review when they use confirmed-fact language.

## Consequences

Positive:

- Writer/Reviewer/Editor stay AgentScope-first without owning persistence.
- Report markdown and dashboard JSON are generated from the same structured sections.
- Evidence maps are built from report item lineage instead of hand-written prose.
- Review results and issues become first-class persisted objects.
- The writing loop can be tested with agents that perform no repository side effects.
- A deterministic uncertainty guard protects against one of Connor.ai's core quality failures.

Trade-offs:

- The markdown renderer is intentionally conservative and template-like for now.
- The early-signal fact-language guard is heuristic; future phases can add stronger semantic review.
- Editor currently revises the latest report by default when no report id is provided, which is practical for the loop but should be surfaced clearly in future API contracts.

## Rejected Alternatives

Let Writer create final markdown only.

- Rejected because the dashboard requires structured JSON, evidence maps, and traceable item lineage.

Let Reviewer pass/fail only in natural language.

- Rejected because writing gates need persistent `ReviewResult` and `ReviewIssue` records.

Let agents write repositories directly.

- Rejected because persistence and trace boundaries must remain Connor-owned and replayable.
