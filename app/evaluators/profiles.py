"""Evaluator role profiles and validation rules."""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.outputs import EvaluationDraft
from app.domain import AgentRole, CandidateCategory, EvaluationDecision, EvaluationType, EventCluster


EVALUATOR_ROLES = {
    AgentRole.FRONTIER_EVALUATOR,
    AgentRole.EVENT_EVALUATOR,
    AgentRole.MARKET_EVALUATOR,
}


class EvaluatorProfileError(ValueError):
    """Raised when an evaluator output violates its role profile."""


@dataclass(frozen=True)
class EvaluatorProfile:
    """Role-level policy for one evaluator agent."""

    role: AgentRole
    evaluator_type: EvaluationType
    allowed_categories: frozenset[CandidateCategory]
    allowed_decisions: frozenset[EvaluationDecision]
    required_score_dimensions: frozenset[str]
    guidance: str

    def validate_draft(self, draft: EvaluationDraft, cluster: EventCluster) -> None:
        """Validate a proposed evaluation against the role and cluster."""

        if draft.evaluator_type != self.evaluator_type:
            raise EvaluatorProfileError(
                f"{self.role.value} must emit {self.evaluator_type.value} evaluations"
            )
        if cluster.category not in self.allowed_categories:
            allowed = ", ".join(sorted(category.value for category in self.allowed_categories))
            raise EvaluatorProfileError(
                f"{self.role.value} cannot evaluate {cluster.category.value}; allowed: {allowed}"
            )
        if draft.decision not in self.allowed_decisions:
            allowed = ", ".join(sorted(decision.value for decision in self.allowed_decisions))
            raise EvaluatorProfileError(
                f"{self.role.value} cannot emit {draft.decision.value}; allowed: {allowed}"
            )

        missing_dimensions = self.required_score_dimensions.difference(draft.dimension_scores)
        if missing_dimensions:
            missing = ", ".join(sorted(missing_dimensions))
            raise EvaluatorProfileError(
                f"{self.role.value} evaluation is missing score dimensions: {missing}"
            )

        for dimension, score in draft.dimension_scores.items():
            if score < 0 or score > 10:
                raise EvaluatorProfileError(
                    f"{self.role.value} score {dimension} must be between 0 and 10"
                )
        if draft.total_score < 0 or draft.total_score > 10:
            raise EvaluatorProfileError(
                f"{self.role.value} total_score must be between 0 and 10"
            )

        if draft.decision == EvaluationDecision.SELECT_EARLY_SIGNAL:
            if self.evaluator_type != EvaluationType.FRONTIER:
                raise EvaluatorProfileError("only frontier evaluator can select early signals")
            if not draft.required_followups:
                raise EvaluatorProfileError("select_early_signal requires required_followups")

        if draft.decision == EvaluationDecision.SELECT_CONFIRMED:
            if draft.missing_evidence:
                raise EvaluatorProfileError("select_confirmed cannot include missing_evidence")
            if draft.total_score < 6:
                raise EvaluatorProfileError("select_confirmed requires total_score >= 6")

        if draft.decision in {
            EvaluationDecision.FOLLOWUP_NOW,
            EvaluationDecision.FOLLOWUP_LATER,
            EvaluationDecision.SHORT_WATCH,
        } and not draft.required_followups:
            raise EvaluatorProfileError(
                f"{draft.decision.value} requires at least one required_followup"
            )

        if draft.decision == EvaluationDecision.RECLUSTER and not draft.risk_flags:
            raise EvaluatorProfileError("recluster requires risk_flags explaining the issue")

        if self.evaluator_type == EvaluationType.MARKET and draft.decision in {
            EvaluationDecision.SELECT_CONFIRMED,
            EvaluationDecision.FOLLOWUP_NOW,
            EvaluationDecision.FOLLOWUP_LATER,
        }:
            if not (cluster.tickers or "ticker" in cluster.metadata or "tickers" in draft.metadata):
                raise EvaluatorProfileError(
                    "market evaluations require ticker or explicit ticker metadata"
                )

    def prompt_extension(self) -> str:
        """Return a compact system-prompt extension for this evaluator role."""

        categories = ", ".join(sorted(category.value for category in self.allowed_categories))
        decisions = ", ".join(sorted(decision.value for decision in self.allowed_decisions))
        dimensions = ", ".join(sorted(self.required_score_dimensions))
        return (
            "Evaluator profile:\n"
            f"- Evaluator type: {self.evaluator_type.value}\n"
            f"- Allowed cluster categories: {categories}\n"
            f"- Allowed decisions: {decisions}\n"
            f"- Required score dimensions: {dimensions}\n"
            f"- Guidance: {self.guidance}\n"
            "Return evaluation_drafts with cluster_id, evaluator_type, dimension_scores, "
            "total_score, decision, reasoning_summary, risk_flags, required_followups, "
            "and missing_evidence."
        )

    def task_profile(self) -> dict[str, object]:
        """Serialize profile details into task context."""

        return {
            "role": self.role.value,
            "evaluator_type": self.evaluator_type.value,
            "allowed_categories": [category.value for category in self.allowed_categories],
            "allowed_decisions": [decision.value for decision in self.allowed_decisions],
            "required_score_dimensions": sorted(self.required_score_dimensions),
            "guidance": self.guidance,
        }


class EvaluatorProfileRegistry:
    """Registry of evaluator role profiles."""

    def __init__(self, profiles: list[EvaluatorProfile]):
        self._profiles = {profile.role: profile for profile in profiles}

    def require(self, role: AgentRole) -> EvaluatorProfile:
        profile = self._profiles.get(role)
        if profile is None:
            raise EvaluatorProfileError(f"evaluator profile not registered: {role.value}")
        return profile

    def list_profiles(self) -> list[EvaluatorProfile]:
        return list(self._profiles.values())


def create_default_evaluator_profile_registry() -> EvaluatorProfileRegistry:
    """Create the default Phase 10 evaluator profile set."""

    return EvaluatorProfileRegistry(
        [
            EvaluatorProfile(
                role=AgentRole.FRONTIER_EVALUATOR,
                evaluator_type=EvaluationType.FRONTIER,
                allowed_categories=frozenset(
                    {
                        CandidateCategory.EARLY_SIGNAL,
                        CandidateCategory.CODE_MODEL,
                        CandidateCategory.RESEARCH,
                        CandidateCategory.OTHER,
                    }
                ),
                allowed_decisions=frozenset(
                    {
                        EvaluationDecision.SELECT_EARLY_SIGNAL,
                        EvaluationDecision.SHORT_WATCH,
                        EvaluationDecision.FOLLOWUP_NOW,
                        EvaluationDecision.FOLLOWUP_LATER,
                        EvaluationDecision.RECLUSTER,
                        EvaluationDecision.ARCHIVE,
                        EvaluationDecision.REJECT,
                    }
                ),
                required_score_dimensions=frozenset(
                    {
                        "information_gap",
                        "specificity",
                        "source_proximity",
                        "potential_impact",
                        "trackability",
                    }
                ),
                guidance=(
                    "Accept unconfirmed but specific and trackable frontier signals; do not "
                    "require official confirmation, but always preserve uncertainty and follow-up points."
                ),
            ),
            EvaluatorProfile(
                role=AgentRole.EVENT_EVALUATOR,
                evaluator_type=EvaluationType.EVENT,
                allowed_categories=frozenset(
                    {
                        CandidateCategory.CONFIRMED_EVENT,
                        CandidateCategory.OFFICIAL_UPDATE,
                    }
                ),
                allowed_decisions=frozenset(
                    {
                        EvaluationDecision.SELECT_CONFIRMED,
                        EvaluationDecision.FOLLOWUP_NOW,
                        EvaluationDecision.RECLUSTER,
                        EvaluationDecision.ARCHIVE,
                        EvaluationDecision.REJECT,
                    }
                ),
                required_score_dimensions=frozenset(
                    {
                        "confirmation_strength",
                        "impact_scale",
                        "expectation_change",
                        "product_impact",
                    }
                ),
                guidance=(
                    "Select only confirmed facts with no missing evidence; connect official "
                    "events to earlier signals when lineage exists."
                ),
            ),
            EvaluatorProfile(
                role=AgentRole.MARKET_EVALUATOR,
                evaluator_type=EvaluationType.MARKET,
                allowed_categories=frozenset({CandidateCategory.TECH_FINANCE}),
                allowed_decisions=frozenset(
                    {
                        EvaluationDecision.SELECT_CONFIRMED,
                        EvaluationDecision.FOLLOWUP_NOW,
                        EvaluationDecision.FOLLOWUP_LATER,
                        EvaluationDecision.RECLUSTER,
                        EvaluationDecision.ARCHIVE,
                        EvaluationDecision.REJECT,
                    }
                ),
                required_score_dimensions=frozenset(
                    {
                        "ai_relevance",
                        "market_impact",
                        "supply_chain_impact",
                        "ticker_relevance",
                    }
                ),
                guidance=(
                    "Require a clear AI-to-market implication chain with tickers, supply-chain "
                    "path, or explicit financial exposure."
                ),
            ),
        ]
    )
