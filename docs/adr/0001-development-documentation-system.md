# ADR 0001: Development Documentation System

Date: 2026-07-03

Status: Accepted

## Context

Connor.ai is a long-running multi-agent intelligence system. The product itself emphasizes traceability, replayability, evidence lineage, and review. The development process should follow the same principle.

The project also has a large architecture surface:

- AgentScope 2.0 integration.
- Connor loop harness.
- Domain schemas.
- Database persistence.
- Tool contracts.
- Evaluation gates.
- Watchlist, archive, and intelligence threads.
- Writing and review loops.

Without a durable written archive, decisions can become implicit and fragile.

## Decision

The project will maintain a documentation archive from the beginning.

Canonical files:

- `docs/MASTER_PLAN.md`: the current full project plan.
- `docs/PROGRESS.md`: phase-level progress tracker.
- `docs/DEV_LOG.md`: chronological development log.
- `docs/adr/`: architecture decision records.
- `docs/plans/`: detailed implementation plans per phase or feature.
- `docs/logs/`: deeper execution notes when a step is too detailed for `DEV_LOG.md`.

Every meaningful implementation step must document:

- What was done.
- Why it was done.
- What files changed.
- What checks were run.
- What effect was achieved.
- What remains open.

## Consequences

Benefits:

- The project remains understandable over time.
- Future agents and humans can reconstruct how decisions were made.
- Development process mirrors the runtime traceability goal.
- Phase transitions become explicit and reviewable.

Costs:

- Each implementation step has a small documentation overhead.
- Documentation can drift if not updated as part of the definition of done.

To control drift, documentation updates are part of phase completion criteria.

