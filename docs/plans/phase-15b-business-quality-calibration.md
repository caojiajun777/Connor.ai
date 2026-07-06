# Phase 15B Plan: Business Quality Calibration

Status: Complete (2026-07-06)

## Goal

Improve the business substance of Connor.ai daily intelligence reports by addressing evidence quality, evaluator decision calibration, finance content extraction, and report usefulness.

## Completed Changes

### Slice 1: Evidence URL Deduplication
- Added `EvidenceRepository.list_urls_in_run()` query method
- Added `ToolExecutor._normalize_url()` for canonical URL comparison (strip trailing slash, normalize http→https, strip www)
- Modified `ToolExecutor._persist_evidence()` to skip duplicate URLs within a run
- Dedup is application-level, within-run only; `url=None` items are never deduped
- Trace events record dedup statistics

### Slice 2: Evaluator Write-Policy Calibration
- Added `WritePolicy` enum to domain (`write_now`, `write_with_caveat`, `archive`, `do_not_write`, `context_only`)
- Added `write_policy: WritePolicy | None` field to `EvaluationResult` domain model
- Added `write_policy` column to `EvaluationResultRecord` ORM model
- Created Alembic migration `0002_add_write_policy_to_evaluations.py`
- Implemented `_calibrate_write_policy()` in `EvaluatorOutputMaterializer` with score-aware rules
- Updated `WritingTaskFactory._write_policy()` to use persisted `write_policy` with fallback to legacy logic
- Calibration rules: SELECT → write_now, FOLLOWUP_NOW → write_with_caveat, FOLLOWUP_LATER with score≥7 → write_with_caveat, REJECT with strong evidence → archive, etc.

### Slice 3: SEC Filing Content Extraction
- Added `sec_filing_content_tool()` to fetch EDGAR filing HTML and extract key sections
- Added `_sec_extract_html_text()` for plain-text extraction from SEC HTML
- Added `_sec_extract_key_sections()` for identifying Risk Factors, MD&A, and Business sections
- Registered tool for Finance Scout with 90s timeout
- Graceful error handling: malformed HTML falls back to raw text

### Slice 4: Finance Figure Context
- Added `_format_financial_value()` helper for human-readable financial numbers ($13.1B, etc.)
- Enhanced `sec_company_facts_tool()` with YoY comparison logic (groups facts by concept, finds prior period)
- Added `with_context` parameter (default True) for opt-in enrichment
- Updated snippet generation with formatted values and YoY change percentages
- Added `formatted_value`, `prior_value`, `yoy_change_pct` to item metadata

### Slice 5: Report Usefulness Tuning
- Added source diversity tracking to writer context (`available_source_types`, `source_type_count`, `source_diversity_warning`)
- Added impact chain rules to quality contract (specific market/product/competitive implications)
- Added follow-up specificity rules (no generic "monitor for updates")
- Added `_repair_generic_followups()` to writing materializer replacing vague follow-ups with context-specific ones

## Verification

- All 182 non-smoke tests pass
- New tests cover URL dedup, finance formatting, and calibration
- All existing tests updated for new behavior (e.g., formatted financial values in snippets)
