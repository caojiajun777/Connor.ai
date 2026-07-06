# Phase 16A Worklog: Daily Report Business Quality Calibration

Date: 2026-07-06

## Used

- AgentScope role registry and AgentRunner ReAct instructions.
- Connor loop harness collect gate and evaluator materialization.
- Writer materializer deterministic Markdown rendering.
- Clusterer materialization boundary.
- Existing SEC source tools: `sec_company_filings`, `sec_filing_content`, and `sec_company_facts`.
- Pytest and Ruff for regression checks.

## Did

- Downgraded very weak single-source community Early Signals from `select_early_signal` to `short_watch`.
- Changed collect bucket coverage so `context_only` / watch-only evaluations do not get promoted into the main report.
- Allowed Finance Scout a bounded two-tool SEC chain, so filing metadata can be followed by filing content or company facts.
- Added SEC metadata-only repair in Tech-Finance report items, including concrete follow-up text for filing content and XBRL facts.
- Split overbroad official-update clusters when unrelated official candidates are grouped together.
- Kept valid early-signal plus official-confirmation clusters intact.
- Added source links to human Markdown report items.
- Filtered source-diversity gate text and internal IDs from human Markdown.
- Counted body items separately from Watchlist items in report statistics.
- Added writer context rules for Chinese body copy and for keeping internal IDs in JSON/evidence maps only.

## How

- `EvaluatorOutputMaterializer` now inspects cluster evidence before persisting Frontier decisions. A single weak community item with low engagement becomes `SHORT_WATCH` with `WritePolicy.CONTEXT_ONLY`.
- `QualityGateService` now respects persisted `write_policy` when adding report-bucket coverage.
- `AgentRunner` generates a Finance Scout-specific tool completion rule instead of using the generic stop-after-first-tool rule.
- `ScoutTaskFactory` gives Finance Scout a dedicated two-call SEC policy while other scouts remain one-call bounded.
- `ClusterOutputMaterializer` splits official-only overbroad drafts by candidate/topic signature, but skips splitting mixed early-signal/confirmation clusters.
- `WritingOutputMaterializer` renders Markdown from normalized structured sections, adds source links from persisted evidence, cleans internal IDs, and repairs SEC metadata-only finance items.

## Problems

- Initial official-cluster splitting was too aggressive and broke the valid pattern where an early signal is merged with its official confirmation.
- The existing generic ReAct rule conflicted with finance analysis because it required every Scout to stop after the first successful tool call.
- Early Signal uncertainty repair reused research/preprint language for non-paper social/product signals.
- The first full smoke report still leaked a system-style overview sentence: `WARNING: Only SEC filings source type available...`.

## Solutions

- Restricted overbroad cluster splitting to clusters where every candidate is already official/confirmed.
- Added a role-specific Finance Scout completion rule and increased Finance Scout limits to two tools / three ReAct iterations.
- Split uncertainty language by category: research items keep preprint wording; non-research Early Signals use source-signal/corroboration wording.
- Expanded human-overview filtering to remove warning/source-type/justification/cross-source-validation gate text from Markdown.

## Checks

- `python -m ruff check ...` passed for changed app and test files.
- `python -m pytest tests\writing tests\evaluators tests\harness tests\clusterer tests\agents tests\tools -q` passed with 139 tests.
- `python -m pytest -q --ignore=tests\smoke` passed with 188 tests.
- `python -m pytest tests\smoke\test_full_daily_cycle.py -v -s` passed with one completed run: `run_2026-07-05_2c4ac7ba7ee753e3`.

## Smoke Report Review

- Improved: weak community Early Signals did not get forced into the main report.
- Improved: Tech-Finance item included SEC filing metadata, source links, and concrete follow-up instructions to use filing content and company facts.
- Improved: Markdown statistics separated body items from Watchlist items.
- Remaining quality gap: the run selected only one Tech-Finance body item because other scouts did not return writeable selected material in that smoke cycle.
- Remaining quality gap: some LLM-generated body copy is still English even though the deterministic report shell and writer rules prefer Chinese body text.
