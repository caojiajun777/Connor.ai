# ADR 0003: Watchlist, Archive, and Intelligence Thread Lifecycle

Date: 2026-07-03

Status: Accepted

## Context

Connor.ai must track frontier signals over time, but active tracking can become expensive if the watchlist grows without bounds. At the same time, expired signals should not be deleted, because historical signals can later become useful context for reasoning about product timelines, source quality, and market/technology evolution.

## Decision

Connor.ai separates short-term active tracking from long-term memory.

Three concepts are used:

- `WatchlistItem`: active, cost-controlled tracking item.
- `ArchivedSignal`: inactive historical signal that is no longer actively checked.
- `IntelligenceThread`: long-term logic chain connecting signals, watches, archives, confirmations, reversals, and later outcomes.

Watchlist items must include:

- `watch_tier`
- `ttl_days`
- `watch_until`
- `priority`
- `revisit_cadence_days`
- `last_checked_at`
- `last_signal_at`
- `decay_score`
- `reactivation_rules`
- `status`

Tier rules:

```text
Short Watch:      3-7 days, leaks, gray rollouts, community signals.
Event Watch:      7-21 days, launches, earnings windows, regulatory events.
Strategic Watch:  30-90 days, Blackwell, HBM, CoWoS, AI capex, ASIC trends.
Archive:          no active tracking, preserved as historical memory.
```

Archived signals must retain lineage to an original cluster or watch item.

Intelligence thread entries must link to at least one cluster, watchlist item, archive item, or report.

## Consequences

Benefits:

- Active daily cost remains bounded.
- Expired signals are not lost.
- Future agents can use historical logic chains without rechecking every old signal.
- Early signals can later be marked as confirmed, disproven, stale, or unresolved.

Costs:

- Later phases need reactivation logic and thread-query support.
- The database layer must preserve historical lineage rather than hard-deleting expired watch items.

## Validation

Phase 1 includes schema validation for watch TTL windows, archive lineage, and intelligence thread timeline links.