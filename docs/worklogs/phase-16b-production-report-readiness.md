# Phase 16B Worklog: Production Report Readiness

Date: 2026-07-06

## Used

- AgentScope agents, ReAct loop, tool calls, and structured output validation.
- Connor `DailyRunHarness`, collect loop, writing loop, quality gates, and materializers.
- Fast local SQLite CLI runs with live DeepSeek-backed AgentScope agents.
- Existing source tools for arXiv, official feeds, SEC filings, Hacker News, GitHub, and Hugging Face.
- Pytest, Ruff, and report artifact inspection scripts.

## Did

- Added `HarnessConfig.commit_checkpoints` and enabled it in the CLI production run path.
- Added checkpoint commits for run creation, phase transitions, task progress, gate decisions, snapshots, and failures.
- Suppressed payload-diff warnings for mutable upsert records: runs, event clusters, watchlist items, intelligence threads, and daily reports.
- Raised Scout `max_iters` from 3 to 4 while keeping the tool budgets fixed.
- Added Watchlist Agent timeout tolerance: failures are traced, evaluation memory can still sync, and the main report can continue.
- Added deterministic Editor fallback after timeout or structured repair failure.
- Enforced report body Chinese at field level instead of accepting a single Chinese sentence anywhere in an item.
- Fixed mixed unrelated official/early cluster splitting.
- Always rendered Early Signals, Confirmed Events, and Tech-Finance sections, with explicit empty states.
- Localized Watchlist update/status text and enum-like status labels such as `confirmed_event` and `active`.
- Collapsed repeated uncertainty prefixes introduced by writer/editor loops.
- Removed known private-company pseudo tickers such as `ANTH`.
- Rewrote SEC metadata-only finance impact text to avoid unsupported stock-move percentages.

## How

- `HarnessContext.checkpoint()` now flushes and optionally commits when `commit_checkpoints=True`.
- CLI creates `HarnessConfig(min_selected_items=2, min_report_body_items=2, commit_checkpoints=True)`.
- Collect-loop task execution now differentiates critical and non-critical agent failures: Scouts and Watchlist can continue when configured; Clusterer and Evaluators still fail fast.
- `AgentRunner._deterministic_structured_fallback()` now supports `EditorOutput` by carrying forward the latest report draft from `editor_context`.
- `WritingOutputMaterializer` now owns deterministic presentation cleanup: source links, empty sections, Chinese status labels, Watchlist localization, ticker sanitation, uncertainty-prefix cleanup, and conservative SEC metadata-only finance impact.
- `ClusterOutputMaterializer` splits unrelated mixed confirmation clusters by candidate topic signature while preserving valid early-signal-to-official-confirmation links.

## Problems

- A foreground CLI run timed out before any committed run state was visible from `status`.
- Real runs produced repository warning noise for legitimate Run/DailyReport/EventCluster updates.
- Official Hugging Face updates were previously mixed with unrelated HN/community items and written under Early Signals.
- LLM drafts sometimes left English template text or enum values in human Markdown.
- Watchlist Agent and Editor model calls could time out and fail the entire run.
- A Tech-Finance report with only SEC metadata invented stock-move percentages.
- A report treated Anthropic as ticker `ANTH`.

## Solutions

- Added production checkpoints and verified that in-progress runs are visible from another CLI status process.
- Kept collision warnings for append-like records but disabled them for mutable records that are intentionally upserted.
- Added mixed-cluster splitting and a regression test for unrelated official plus HN clusters.
- Added deterministic language and status sanitation for report items and Watchlist text.
- Added Watchlist non-critical failure handling and Editor deterministic fallback.
- Added SEC metadata-only finance impact rewrite: the report now states that filing existence alone cannot support beat/miss, capex direction, or stock-price impact.
- Added invalid ticker filtering for known private/non-public company markers.

## Checks

- `python -m ruff check .` passed.
- `python -m pytest -q --ignore=tests\smoke` passed with 198 tests.
- `git diff --check` passed; Git emitted one line-ending warning for `tests/harness/test_daily_run_harness.py`.
- Real CLI run `phase16c` completed with repository warnings removed and stable section rendering.
- Real CLI run `phase16d` exposed Watchlist timeout failure; fixed with Watchlist tolerance.
- Real CLI run `phase16e` exposed Editor timeout failure; fixed with Editor fallback.
- Real CLI run `phase16f` completed with 42 evidence items, 18 candidates, 12 clusters, 12 evaluations, 4 Watchlist items, 1 report, and empty stderr.

## Final Smoke Review

- Completed run: `run_2026-07-05_e0541abd3b5042f3`.
- Final report: `report_cccef7130cb2ff5d`.
- Markdown and JSON artifacts were written to `test_tmp/phase16f_report`.
- Human Markdown had no internal IDs, no source-diversity/debug markers, no raw Watchlist template text, and no repeated uncertainty prefixes.
- The three core body sections were present even when Tech-Finance had no writeable item.
- Remaining product-level improvement: report quality is now showable, but future work should add scheduler/worker deployment, Dashboard frontend, source catalog management, and deeper finance extraction before calling the entire system production deployed.
