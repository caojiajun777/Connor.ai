# Phase 8 Plan: All Scouts

Status: Complete

Completed: 2026-07-03

## Goal

Expand Phase 7 from one Social Scout closed loop into all five Scout roles:

```text
Social Scout
Code & Model Scout
Research Scout
Official Scout
Finance Scout
```

This phase does not add broad real source adapters yet. It completes the Scout role layer: each Scout has its own source boundary, candidate category boundary, signal-status policy, follow-up requirements, task template, prompt extension, and materialization validation.

## Delivered Architecture

Added:

```text
app/scouts/__init__.py
app/scouts/profiles.py
app/scouts/tasks.py
```

Updated:

```text
app/agents/registry.py
app/harness/materialization.py
```

## Scout Profiles

Each Scout now has a `ScoutProfile` with:

- allowed source types
- allowed candidate categories
- allowed signal statuses
- required follow-up behavior
- focus topics
- AgentTask template
- optional evidence-strength requirements
- optional ticker or impact-chain requirement

The five default profiles are:

| Scout | Main categories | Role boundary |
|---|---|---|
| Social Scout | `early_signal` | Community reports, gray rollouts, researcher hints, small-circle discussion. |
| Code & Model Scout | `code_model`, `early_signal` | GitHub, Hugging Face, packages, SDK or model upload anomalies. |
| Research Scout | `research`, `early_signal` | Papers, benchmarks, reasoning, agent, and multimodal research signals. |
| Official Scout | `confirmed_event`, `official_update` | Official blogs, API changelogs, docs, model releases, pricing or product updates. |
| Finance Scout | `tech_finance` | AI capex, semiconductor supply chain, data-center revenue, guidance, and ticker impact. |

Development tools such as `manual_seed` and `mock_search` remain allowed through explicit development source types, so deterministic tests can run without external source dependencies.

## Prompt and Task Integration

`create_default_agent_role_registry` now appends each Scout's profile constraints to its AgentScope system prompt.

`ScoutTaskFactory` creates `AgentTask` objects with:

- the role-specific task template
- the Scout profile payload
- the candidate output contract
- any run-specific context passed by the harness or orchestrator

This keeps AgentScope responsible for agent execution while Connor supplies product constraints in a structured, testable way.

## Materialization Validation

`ScoutOutputMaterializer` now validates each `CandidateDraft` against the producing Scout's profile before creating a `CandidateItem`.

Validation catches:

- wrong candidate category for the Scout
- wrong signal status
- missing follow-up questions
- insufficient evidence-strength claims for official updates
- Finance Scout items missing tickers or impact chains
- evidence source types outside the role boundary

If a Scout violates its profile, materialization raises `HarnessError` and the candidate is not persisted.

## Closed-Loop Coverage

Added:

```text
tests/scouts/test_profiles.py
tests/harness/test_all_scouts_closed_loop.py
```

Coverage:

- Default profile registry covers all Scout roles.
- Scout task factory embeds profile context and output contract.
- Finance Scout rejects non-finance candidates.
- Official Scout requires strong or official evidence strength.
- All five Scouts run through AgentScope `ToolCallBlock`.
- Connor `manual_seed` creates evidence for each Scout.
- Each Scout returns a valid role-specific `candidate_drafts` payload.
- Materializer creates five candidates.
- Single-agent bootstrap creates five clusters and evaluations.
- Collect gate enters writing with five selected clusters.
- Invalid Finance Scout output is rejected before persistence.

## Checks Run

- `python -m pytest tests\scouts tests\harness\test_all_scouts_closed_loop.py tests\harness\test_single_agent_closed_loop.py tests\agents\test_registry.py -q`: 8 passed.
- `python -m pytest -q`: 52 passed.
- `python -m compileall app tests`: passed.

## Non-Goals Preserved

- No full production Clusterer yet.
- No production Evaluator group yet.
- No real external source expansion yet.
- No dashboard or FastAPI changes yet.

## Follow-up Phase

Phase 9 should replace bootstrap clustering with a real Clusterer:

- group multiple candidates into event clusters
- preserve conflicting evidence
- generate canonical claims
- link early signals to later official confirmations
