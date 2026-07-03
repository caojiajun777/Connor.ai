# ADR 0010: Scout Profile Boundaries

Date: 2026-07-03

Status: Accepted

## Context

Phase 7 proved one Social Scout can run through AgentScope, call a Connor tool, create evidence, return a candidate draft, and let the Connor harness materialize candidate, cluster, evaluation, trace, and run lineage.

Phase 8 needs all Scout roles without collapsing them into one generic "search agent." The system needs role-specific autonomy, but not unbounded output. Each Scout should be free to explore within AgentScope, while Connor should still decide what can be persisted.

## Decision

Add a `ScoutProfile` layer.

Each profile defines:

- role
- display name
- allowed source types
- allowed candidate categories
- allowed signal statuses
- required follow-up behavior
- task template
- focus topics
- optional evidence-strength requirements
- optional ticker or impact-chain requirements

AgentScope receives profile constraints through role prompts and task context.

Connor loop harness enforces profile constraints at the materialization boundary before creating `CandidateItem` records.

## Boundary

AgentScope owns:

- agent execution
- tool-call loop
- role prompt interpretation
- final structured Scout output

Connor harness owns:

- run state
- Scout profile validation
- evidence lookup
- candidate persistence
- trace events
- bootstrap cluster/evaluation until Phase 9/10 replace them

This keeps AgentScope as the first-choice agent framework without creating a Connor-owned agent runtime contract.

## Development Source Types

`manual_seed` and `mock_search` remain accepted for deterministic development and tests through explicit development source types.

This lets the Scout profile layer be tested fully before real external adapters are introduced.

## Consequences

Benefits:

- Five Scouts now have distinct responsibilities.
- Invalid Scout outputs are rejected before persistence.
- Early signals remain intentionally permissive but must be trackable.
- Official and finance items get stricter role-specific gates.
- Future source adapters can attach to profiles without changing materialization semantics.

Costs:

- Profile rules must be maintained as source coverage expands.
- Some source-type boundaries are still broad during development because deterministic seed tools are allowed.
- Bootstrap cluster/evaluation remains temporary until Phase 9 and Phase 10.

## Validation

Phase 8 validates:

- profile registry coverage for all Scout roles
- role-specific AgentTask creation
- AgentScope all-Scout tool loop
- candidate materialization for Social, Code & Model, Research, Official, and Finance Scouts
- invalid profile output rejection

Checks:

- `python -m pytest tests\scouts tests\harness\test_all_scouts_closed_loop.py tests\harness\test_single_agent_closed_loop.py tests\agents\test_registry.py -q`: 8 passed.
- `python -m pytest -q`: 52 passed.
- `python -m compileall app tests`: passed.
