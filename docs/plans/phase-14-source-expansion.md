# Phase 14 Plan: Source Expansion

Status: In progress

Started: 2026-07-04

Completed slices:

- GitHub / Hugging Face source tools
- arXiv / OpenReview source tools
- official blog / API changelog source tools
- SEC / investor-relations source tools
- Hacker News source tool

## Goal

Expand Connor.ai from deterministic seed/mock tools into real public-source collection while preserving the existing tool, evidence, artifact, and trace boundaries.

This phase should not let agents scrape or persist source data ad hoc. Real sources enter Connor through registered tools that return `ToolEnvelope` objects, are converted into `EvidenceItem` records by `ToolExecutor`, and are recorded as traceable tool calls.

## First Source Group

Implemented:

- GitHub repository search
- GitHub code search
- Hugging Face model search
- Hugging Face dataset search

These were chosen first because they fit the Code & Model Scout and Research Scout contracts, produce structured public metadata, and exercise the same evidence path needed by later source groups.

## Second Source Group

Implemented:

- arXiv paper search
- OpenReview note search

These extend the same public source boundary into research signals. arXiv returns Atom XML, so the source helper now supports text responses in addition to JSON. OpenReview API 2 is wired through the documented `/notes` endpoint, but anonymous live access may return a challenge response; the tool treats that as a traceable source failure instead of bypassing the access boundary.

## Third Source Group

Implemented:

- official RSS/Atom feed search
- official API changelog feed/page search

These extend Connor into confirmed first-party updates for the Official Scout. The implementation uses a curated source catalog rather than arbitrary agent-provided URLs. Feed sources are parsed as RSS/Atom entries; changelog pages are parsed into heading sections so official API updates can still become normalized evidence when no stable feed exists.

## Fourth Source Group

Implemented:

- SEC recent company filings
- SEC XBRL company facts
- curated investor-relations page search

These extend Connor into Tech-Finance collection for Finance Scout. SEC tools use official EDGAR JSON endpoints and resolve ticker symbols through SEC's company ticker map. Investor-relations search uses a curated company catalog rather than arbitrary URLs, then normalizes main-page sections into evidence.

## Fifth Source Group

Implemented:

- Hacker News official API feed search

This extends Connor into community-source collection for Social Scout using Hacker News' official Firebase API. The tool fetches bounded story feeds, retrieves bounded item details, filters locally by query, and normalizes matching community items into evidence. Reddit, X/Twitter, and other authenticated or policy-sensitive social sources remain follow-ups until credential, rate-limit, and content-policy behavior is explicit.

## Delivered Architecture

Added:

```text
app/tools/http.py
app/tools/source_tools.py
tests/tools/test_source_tools.py
docs/plans/phase-14-source-expansion.md
docs/adr/0016-public-source-tool-boundary.md
```

Updated:

```text
README.md
app/config.py
app/tools/__init__.py
app/tools/builtin.py
app/tools/executor.py
docs/PROGRESS.md
docs/DEV_LOG.md
docs/MASTER_PLAN.md
```

## Tool Contract

New registered tools:

- `github_repository_search`
- `github_code_search`
- `huggingface_model_search`
- `huggingface_dataset_search`
- `arxiv_search`
- `openreview_note_search`
- `official_feed_search`
- `api_changelog_search`
- `sec_company_filings`
- `sec_company_facts`
- `investor_relations_search`
- `hacker_news_feed_search`

Each tool:

- accepts a `ToolExecutionContext`
- uses `context.query` as the source search query
- accepts bounded source-specific params such as `per_page`, `page`, `limit`, `sort`, and `order`
- returns a `ToolEnvelope`
- normalizes each source record into `ToolEnvelopeItem`
- does not write database records directly
- does not create trace events directly

The arXiv tool accepts bounded `start`, `max_results`, `sortBy`, and `sortOrder` params and normalizes Atom entries into source items. The OpenReview tool accepts bounded `limit`, `offset`, `sort`, and a narrow set of note filters such as `content.title`, `invitation`, `forum`, and `replyto`.

The official-source tools accept bounded `source_key` / `source_keys`, `max_sources`, `max_results`, and `match_mode` params. They do not accept arbitrary URLs; available source keys are returned in tool metadata so agents can choose from the audited catalog.

The SEC tools accept `ticker` or `cik`, bounded `forms`, bounded `concepts`, `unit`, and `max_results` params. The investor-relations tool accepts the same catalog controls as official-source tools.

The Hacker News tool accepts bounded `feed`, `fetch_limit`, `max_results`, and `match_mode` params. It does not use third-party search APIs and does not fetch arbitrary URLs.

## Runtime Configuration

Added optional settings:

- `CONNOR_GITHUB_TOKEN`
- `CONNOR_HUGGINGFACE_TOKEN`
- `CONNOR_TOOL_USER_AGENT`

Tokens are optional for public endpoints, but can improve rate limits and access behavior.

## Error Behavior

HTTP failures are converted into retryable or non-retryable `ToolError` entries inside the returned `ToolEnvelope`.

This means:

- expected source failures do not crash a run
- failed tool calls are still traceable
- source rate-limit metadata is preserved when available
- unexpected tool exceptions still flow through `ToolExecutor` failure handling

## Executor Boundary

`ToolSpec.timeout_seconds` now becomes an execution default. If a caller does not pass `timeout_seconds` in `ToolExecutionContext.params`, `ToolExecutor` injects the registered default into the effective context before calling the tool.

This keeps timeout policy consistent across:

- registered tool metadata
- actual HTTP calls
- tool-call request artifacts
- trace payloads

## References

- GitHub REST Search API: `https://docs.github.com/en/rest/search/search`
- Hugging Face Hub API: `https://huggingface.co/docs/hub/en/api`
- arXiv API User Manual: `https://info.arxiv.org/help/api/user-manual.html`
- OpenReview API 2 OpenAPI: `https://api2.openreview.net/docs/api.yml`
- OpenAI News RSS: `https://openai.com/news/rss.xml`
- Google AI Blog RSS: `https://blog.google/technology/ai/rss/`
- GitHub Changelog RSS: `https://github.blog/changelog/feed/`
- OpenAI API Changelog: `https://developers.openai.com/api/docs/changelog`
- SEC EDGAR APIs: `https://www.sec.gov/search-filings/edgar-application-programming-interfaces`
- SEC Company Tickers JSON: `https://www.sec.gov/files/company_tickers.json`
- Hacker News Firebase API: `https://github.com/HackerNews/API`

## Checks

- `python -m pytest tests\tools\test_source_tools.py -q`: 28 passed.
- `python -m pytest tests\tools tests\agents\test_registry.py tests\agents\test_runner.py -q`: 42 passed.
- `python -m pytest tests\scouts\test_profiles.py tests\harness\test_all_scouts_closed_loop.py -q`: 6 passed.
- `python -m pytest -q`: 122 passed.
- `python -m compileall app tests`: passed.
- `git diff --check`: passed.

## Effect

Connor.ai can now collect real code/model/research/official/finance/community source evidence through the same audited runtime path as deterministic development tools:

```text
AgentScope Agent
-> Connor FunctionTool
-> ToolExecutor
-> registered public source tool
-> ToolEnvelope
-> EvidenceItem
-> ToolCallRecord / Artifact / TraceEvent
```

## Open Follow-ups

- Add Reddit/X/Twitter/social tools only after rate limits, authentication, and content-policy boundaries are explicit.
- Add source-specific pagination and dashboard filters once real run volume grows.
