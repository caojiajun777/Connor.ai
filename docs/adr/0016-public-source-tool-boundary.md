# ADR 0016: Public Source Tool Boundary

Date: 2026-07-04

Status: Accepted

## Context

Connor.ai's core pipeline is now traceable from AgentScope tool calls through evidence, candidates, clusters, evaluations, watchlist memory, reports, and dashboard API reads.

The next risk is source expansion. Real external APIs can fail, rate-limit, return inconsistent payloads, and tempt direct agent-side scraping. Connor needs real source access without weakening replayability or letting source logic bypass evidence and trace contracts.

## Decision

Implement public source access as first-class Connor tools under `app/tools/source_tools.py`.

Public source tools must:

- be registered through `ToolRegistry`
- declare role permissions through `ToolSpec`
- return `ToolEnvelope`
- normalize records into `ToolEnvelopeItem`
- leave evidence persistence to `ToolExecutor`
- leave artifacts and trace records to `TraceService`
- convert expected HTTP/source failures into `ToolError`
- support optional tokens through `Settings`

The initial source groups use official or first-party public interfaces where available: GitHub and Hugging Face APIs, arXiv Atom, OpenReview API 2, curated official RSS/Atom/changelog sources, SEC EDGAR JSON APIs, curated investor-relations sources, and the Hacker News Firebase API.

A small stdlib HTTP helper under `app/tools/http.py` is enough for the current synchronous tool boundary. It avoids adding a runtime dependency before the worker/queue design is settled.

## Consequences

Positive:

- Real source collection now uses the same audit path as deterministic tools.
- AgentScope agents can explore public code, model, research, official-update, finance, and bounded community sources without direct persistence access.
- Source failures are visible in trace and artifacts instead of becoming silent missing data.
- Optional tokens can be configured without changing agent prompts or tool signatures.
- Tests can inject fake JSON/text clients and avoid live network calls.

Trade-offs:

- Source tools are currently synchronous.
- Pagination is bounded and simple.
- The initial rate-limit metadata normalization favors GitHub-style headers.
- Source adapters intentionally avoid deep provider-specific SDKs until source breadth and worker execution needs are clearer.

## Rejected Alternatives

Let agents browse or call source APIs directly.

- Rejected because evidence, artifacts, and trace records would become inconsistent and hard to replay.

Persist source records inside each source adapter.

- Rejected because tool adapters should not own domain persistence or trace sequencing.

Introduce a full async HTTP stack now.

- Rejected because Connor's current tool execution path is synchronous, and worker/queue architecture is not yet implemented.

Add unauthenticated Reddit/X scraping now.

- Rejected because those sources need explicit credential, rate-limit, platform-policy, and content-boundary handling before they belong in the audited source catalog.
