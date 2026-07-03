# Phase 7 Plan: Single-Agent Closed Loop

Status: Complete

Completed: 2026-07-03

## Goal

Run one real Scout path through the Phase 6 harness:

```text
DailyRunHarness creates run
-> CollectLoopHarness assigns Social Scout
-> AgentScope Agent calls Connor tool
-> ToolExecutor persists EvidenceItem
-> ScoutOutput returns candidate draft
-> Connor materializer creates CandidateItem
-> single-agent bootstrap creates provisional EventCluster + EvaluationResult
-> Collect gate enters writing
```

This phase proves the harness is not only moving preloaded fixtures. It can now accept an AgentScope agent result and turn it into persisted Connor domain state.

## Delivered Architecture

Added:

```text
app/harness/materialization.py
```

Updated:

```text
app/agents/outputs.py
app/harness/collect.py
app/harness/config.py
app/harness/__init__.py
```

## Agent Output Extension

Added `CandidateDraft` and `ScoutOutput.candidate_drafts`.

The Scout can now return:

```json
{
  "summary": "...",
  "evidence_ids": ["..."],
  "candidate_drafts": [
    {
      "category": "early_signal",
      "signal_status": "gray_rollout_feedback",
      "claim_summary": "...",
      "entities": ["OpenAI"],
      "topics": ["api", "reasoning"],
      "uncertainty": "low",
      "evidence_strength": "moderate",
      "why_it_matters": "...",
      "potential_impact": "...",
      "followup_questions": ["..."]
    }
  ]
}
```

The agent does not write database records directly. The harness materializer validates and persists the draft.

## Materialization Boundary

`ScoutOutputMaterializer` creates:

- `CandidateItem`
- `EventCluster` when single-agent bootstrap is active
- `EvaluationResult` when single-agent bootstrap is active
- trace events for candidate, cluster, and evaluation creation
- run lineage updates for candidate and cluster ids

The bootstrap cluster/evaluation path is intentionally marked:

```json
{
  "bootstrap_single_agent": true
}
```

This keeps Phase 7 honest: it proves the loop, but does not pretend to replace the later full Clusterer and Evaluator group.

## Harness Integration

`CollectLoopHarness` now materializes Scout outputs after AgentScope task execution.

Bootstrap cluster/evaluation only runs when:

- Scout candidate materialization is enabled.
- Bootstrap config flags are enabled.
- No explicit Clusterer task is scheduled.
- No explicit Evaluator task is scheduled.

This means later phases can add real Clusterer/Evaluator tasks without fighting the Phase 7 bootstrap path.

## Tests Delivered

Added:

```text
tests/harness/test_single_agent_closed_loop.py
```

Coverage:

- AgentScope model emits `ToolCallBlock`.
- AgentScope Toolkit executes Connor `manual_seed`.
- `ToolExecutor` persists evidence.
- AgentScope final message returns `candidate_drafts`.
- `ScoutOutputMaterializer` persists candidate.
- Single-agent bootstrap creates cluster and evaluation.
- Collect gate enters writing from the generated evaluation.
- Trace timeline includes tool, evidence, candidate, cluster, evaluation, and gate events.

## Checks Run

- `python -m pytest tests\harness -q`: 8 passed.
- `python -m pytest -q`: 46 passed.
- `python -m compileall app tests`: passed.

## Non-Goals Preserved

- No broad real source adapters yet.
- No full Scout role implementation for all sources yet.
- No production Clusterer yet.
- No production Evaluator group yet.
- No writing/report generation changes in this phase.

## Follow-up Phase

Phase 8 should expand from one Scout path to all Scout roles:

- Social Scout
- Code & Model Scout
- Research Scout
- Official Scout
- Finance Scout

Each Scout should get role-specific task templates, source/tool boundaries, and materialization tests.
