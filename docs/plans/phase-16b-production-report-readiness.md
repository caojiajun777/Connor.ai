# Phase 16B Plan: Production Report Readiness

## Goal

Bring the real daily run path closer to a production-ready state: observable while running, resilient to non-critical model timeouts, and strict enough that the generated Markdown can be shown to a human without debug leakage or unsupported market claims.

## Scope

1. Production observability
   - Persist run checkpoints during CLI daily runs.
   - Make in-progress runs visible to `python -m app.cli status` and future API polling.
   - Reduce repository upsert log noise for mutable records.

2. Report structure and language
   - Enforce Simplified Chinese body copy at field level.
   - Always render the three core body sections: Early Signals, Confirmed Events, and Tech-Finance.
   - Render clear empty-state copy when a bucket has no writeable items.
   - Localize enum-like status labels and Watchlist status/development text.

3. Business-quality guards
   - Split unrelated official/early mixed clusters instead of letting one bad model cluster misclassify unrelated events.
   - Collapse repeated uncertainty prefixes after writer/editor revision loops.
   - Remove known private-company pseudo tickers such as `ANTH`.
   - For SEC metadata-only finance items, block unsupported stock-move percentages and force a conservative impact chain.

4. Runtime resilience
   - Give Scout roles enough ReAct iterations to summarize after tool use while preserving tool-call budgets.
   - Allow Watchlist Agent timeouts to be traced and bypassed without failing the main daily report.
   - Add deterministic Editor fallback so an editor timeout can carry forward the latest evidence-bound draft to final review.

## Non-Goals

- No scheduler, worker queue, Docker, or frontend implementation.
- No Reddit/X authentication redesign.
- No source catalog database migration.
- No attempt to make every model-generated judgment perfect; this phase adds deterministic guardrails around high-risk failure modes.

## Verification

- Full non-smoke test suite.
- Ruff and git diff whitespace checks.
- Real CLI daily runs with DeepSeek-backed AgentScope agents and live tools.
- Manual business-quality review of generated Markdown and JSON.
