# Phase 16A Plan: Daily Report Business Quality Calibration

## Goal

Make a completed Connor.ai daily report read like a useful intelligence product, not like a trace/debug artifact.

This phase focuses on deterministic quality improvements inside the existing AgentScope + Connor harness architecture. It does not add queue workers, frontend pages, or new deployment infrastructure.

## Scope

1. Weak Early Signal calibration
   - Keep loose early-signal standards, but downgrade very weak single-source community posts to watch-only context.
   - Prevent bucket coverage logic from promoting `context_only` / `short_watch` items into the main report.

2. Finance follow-up quality
   - Let Finance Scout perform a bounded SEC follow-up chain.
   - Surface SEC metadata-only cases as missing-content follow-ups instead of implying strong market impact.

3. Official cluster precision
   - Split overbroad official-update clusters when multiple official candidates are unrelated announcements.
   - Preserve valid early-signal-to-official-confirmation clustering.

4. Human Markdown cleanup
   - Add inline source links to report items.
   - Hide internal IDs and system quality-gate language from human Markdown.
   - Count body items and watchlist items separately.
   - Tell Writer to use Chinese body copy while preserving English names/tickers.

## Non-Goals

- No scheduler or async worker implementation.
- No dashboard frontend.
- No source-catalog database migration.
- No Reddit/X authentication redesign.

## Verification

- Targeted tests for writing, evaluators, harness gates, clusterer, agents, and tools.
- Full non-smoke test suite.
- Optional full daily smoke run with the real model/API after local tests pass.
