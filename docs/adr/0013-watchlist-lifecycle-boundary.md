# ADR 0013: Watchlist Lifecycle Boundary

Date: 2026-07-04

Status: Accepted

## Context

Phase 10 made evaluator decisions persistent. The next problem is memory cost.

If every early signal stays active forever, Connor.ai will become expensive and noisy over time. But deleting old signals would destroy historical reasoning chains. The system needs a distinction between:

- active watchlist items that cost future attention
- archived signals that preserve history without active polling
- intelligence threads that connect early signals, confirmations, archives, and later outcomes

The Watchlist Agent should help decide what to track, archive, and connect, but the harness must still guarantee TTL expiration and persistence boundaries.

## Decision

Use two cooperating boundaries:

1. `WatchlistOutputMaterializer`

   Materializes Watchlist Agent drafts into `WatchlistItem`, `ArchivedSignal`, and `IntelligenceThread` records.

2. `WatchlistLifecycleService`

   Applies deterministic lifecycle policies around the agent:

   - expire due active/reactivated watch items
   - create default memory from evaluator decisions when no Watchlist Agent task is scheduled

The collect loop always runs expiration during `watchlist_update`. It runs Watchlist Agent materialization when tasks exist. If no Watchlist Agent task exists, it can auto-sync evaluator memory through deterministic policy.

## Consequences

Positive:

- Active watchlist growth is bounded by TTL expiration.
- Archive preserves historical evidence and reactivation hints.
- Intelligence threads keep long-term logic chains without requiring every item to stay active.
- Watchlist Agent remains AgentScope-first, but persistence and trace stay Connor-owned.
- Runs remain usable even before a sophisticated Watchlist Agent prompt is deployed.

Trade-offs:

- Deterministic policy may create conservative default watch items that a future smarter Watchlist Agent would tune more precisely.
- Thread matching is currently deterministic by topic/lineage, not semantic similarity.
- Cross-run thread intelligence is persisted, but semantic retrieval and dashboard UX are future phases.

## Rejected Alternatives

Let Watchlist Agent own expiration.

- Rejected because TTL cleanup must be deterministic and reliable even when no agent task runs.

Delete expired watch items.

- Rejected because Connor.ai needs historical signal chains for later reasoning.

Use only deterministic rules and skip Watchlist Agent.

- Rejected because the Watchlist Agent is part of the intended topology and will eventually make richer tracking decisions than static policy.
