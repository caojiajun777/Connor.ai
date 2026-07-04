# ADR 0012: Evaluator Materialization Boundary

Date: 2026-07-04

Status: Accepted

## Context

Phase 9 introduced real event clusters, but the collect loop still used a marked temporary `bootstrap_clusterer_evaluation` when no Evaluator task existed.

Phase 10 needs three evaluator roles:

- Frontier Evaluator
- Event Evaluator
- Market Evaluator

The system must preserve two constraints:

- AgentScope remains responsible for agent execution and structured tool/model interaction.
- Connor loop harness remains responsible for run state, quality gates, artifact archival, trace persistence, and domain object persistence.

Evaluator behavior also differs by category. Early Signals should be allowed through with looser confirmation standards when they are specific and trackable. Confirmed Events should require stronger evidence. Tech-Finance items should require a clear AI-to-market implication chain.

## Decision

Evaluator agents return `EvaluationDraft` objects through `EvaluatorOutput`.

Connor persists those drafts through `EvaluatorOutputMaterializer`.

Evaluator role rules live in `EvaluatorProfile` objects:

- allowed cluster categories
- allowed decisions
- required score dimensions
- role guidance
- validation rules for follow-up, select-confirmed, select-early-signal, recluster, and market ticker paths

The collect loop injects compact `cluster_context` into evaluator tasks. The default AgentScope role registry injects the relevant evaluator profile into each evaluator's system prompt.

## Consequences

Positive:

- Evaluator agents can explore and judge freely inside AgentScope but must return auditable structured drafts.
- Invalid evaluator output is rejected before persistence.
- Early-signal standards can stay intentionally looser without weakening confirmed-event rules.
- The collect gate now acts on real `EvaluationResult` records instead of clusterer bootstrap evaluations.
- Trace records contain evaluator decisions and created evaluation object references.
- Phase 11 can build Watchlist, Archive, and Intelligence Threads from explicit evaluator decisions and follow-up fields.

Trade-offs:

- The evaluator profile layer is another boundary to maintain.
- Agent prompts and materialization validation must stay aligned when score dimensions change.
- Current execution still runs individual evaluator tasks; AgentScope team/worker orchestration remains future work.

## Rejected Alternatives

Let evaluator agents write database rows directly.

- Rejected because it would bypass Connor's persistence, trace, and validation boundary.

Encode all evaluator rules only in the quality gate.

- Rejected because the gate should route already-materialized decisions, not interpret raw agent output or role-specific scoring policy.

Keep clusterer bootstrap evaluations permanently.

- Rejected because clusterer decisions are not evaluator decisions and would hide the distinction between clustering and judgment.
