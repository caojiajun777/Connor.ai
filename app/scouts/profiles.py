"""Role-specific Scout profiles."""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.outputs import CandidateDraft
from app.domain import (
    AgentRole,
    CandidateCategory,
    EvidenceItem,
    EvidenceStrength,
    SignalStatus,
    SourceType,
)


SCOUT_ROLES = frozenset(
    {
        AgentRole.SOCIAL_SCOUT,
        AgentRole.CODE_MODEL_SCOUT,
        AgentRole.RESEARCH_SCOUT,
        AgentRole.OFFICIAL_SCOUT,
        AgentRole.FINANCE_SCOUT,
    }
)

EARLY_SIGNAL_STATUSES = frozenset(
    {
        SignalStatus.UNCONFIRMED_LEAK,
        SignalStatus.GRAY_ROLLOUT_FEEDBACK,
        SignalStatus.CODE_ANOMALY,
        SignalStatus.RESEARCHER_HINT,
        SignalStatus.COMMUNITY_RUMOR,
        SignalStatus.SINGLE_SOURCE_SIGNAL,
        SignalStatus.MANUAL_HYPOTHESIS,
    }
)

DEVELOPMENT_SOURCE_TYPES = frozenset({SourceType.MANUAL, SourceType.OTHER})


class ScoutProfileError(ValueError):
    """Raised when a Scout output violates its role profile."""


@dataclass(frozen=True)
class ScoutProfile:
    """Static role profile for one Scout."""

    role: AgentRole
    display_name: str
    source_types: frozenset[SourceType]
    allowed_categories: frozenset[CandidateCategory]
    allowed_signal_statuses: frozenset[SignalStatus]
    required_followup_questions: bool
    task_template: str
    focus_topics: tuple[str, ...]
    required_evidence_strengths: frozenset[EvidenceStrength] = frozenset()
    requires_ticker_or_impact: bool = False
    development_source_types: frozenset[SourceType] = DEVELOPMENT_SOURCE_TYPES

    def validate_draft(self, draft: CandidateDraft, evidence_items: list[EvidenceItem]) -> None:
        """Validate an agent-proposed candidate draft before persistence."""

        if draft.category not in self.allowed_categories:
            raise ScoutProfileError(
                f"{self.role.value} cannot create category {draft.category.value}"
            )

        if draft.signal_status not in self.allowed_signal_statuses:
            status = draft.signal_status.value if draft.signal_status else "none"
            raise ScoutProfileError(f"{self.role.value} cannot use signal_status {status}")

        if self.required_followup_questions and not draft.followup_questions:
            raise ScoutProfileError(f"{self.role.value} candidate drafts require followup_questions")

        if self.required_evidence_strengths and draft.evidence_strength not in self.required_evidence_strengths:
            allowed = ", ".join(sorted(str(item.value) for item in self.required_evidence_strengths))
            raise ScoutProfileError(
                f"{self.role.value} requires evidence_strength in {{{allowed}}}"
            )

        if self.requires_ticker_or_impact and not (draft.tickers or draft.potential_impact):
            raise ScoutProfileError(
                f"{self.role.value} candidate drafts require tickers or potential_impact"
            )

        for evidence in evidence_items:
            if not self.accepts_source_type(evidence.source_type):
                raise ScoutProfileError(
                    f"{self.role.value} cannot use evidence source_type {evidence.source_type.value}"
                )

    def accepts_source_type(self, source_type: SourceType) -> bool:
        """Return whether this profile may use a source type."""

        return source_type in self.source_types or source_type in self.development_source_types

    def prompt_extension(self) -> str:
        """Prompt text appended to the AgentScope role prompt."""

        source_values = ", ".join(source.value for source in sorted(self.source_types, key=lambda item: item.value))
        category_values = ", ".join(
            category.value for category in sorted(self.allowed_categories, key=lambda item: item.value)
        )
        return (
            "Scout profile constraints: "
            f"focus_sources=[{source_values}], "
            f"allowed_candidate_categories=[{category_values}], "
            "return candidate_drafts that satisfy this role profile."
        )

    def context_payload(self) -> dict[str, object]:
        """JSON-safe profile payload for AgentTask context."""

        return {
            "role": self.role.value,
            "display_name": self.display_name,
            "source_types": [source.value for source in sorted(self.source_types, key=lambda item: item.value)],
            "allowed_categories": [
                category.value for category in sorted(self.allowed_categories, key=lambda item: item.value)
            ],
            "allowed_signal_statuses": [
                status.value
                for status in sorted(self.allowed_signal_statuses, key=lambda item: item.value)
            ],
            "required_followup_questions": self.required_followup_questions,
            "required_evidence_strengths": [
                strength.value
                for strength in sorted(self.required_evidence_strengths, key=lambda item: item.value)
            ],
            "requires_ticker_or_impact": self.requires_ticker_or_impact,
            "focus_topics": list(self.focus_topics),
        }


class ScoutProfileRegistry:
    """Registry for Scout role profiles."""

    def __init__(self, profiles: list[ScoutProfile]):
        self._profiles = {profile.role: profile for profile in profiles}
        missing_roles = SCOUT_ROLES - set(self._profiles)
        if missing_roles:
            missing = ", ".join(role.value for role in sorted(missing_roles, key=lambda item: item.value))
            raise ValueError(f"missing scout profiles: {missing}")

    def require(self, role: AgentRole) -> ScoutProfile:
        if role not in SCOUT_ROLES:
            raise ScoutProfileError(f"{role.value} is not a Scout role")
        return self._profiles[role]

    def list_profiles(self) -> list[ScoutProfile]:
        return list(self._profiles.values())


def create_default_scout_profile_registry() -> ScoutProfileRegistry:
    """Create the default Phase 8 Scout profile registry."""

    return ScoutProfileRegistry(
        [
            ScoutProfile(
                role=AgentRole.SOCIAL_SCOUT,
                display_name="Social Scout",
                source_types=frozenset(
                    {
                        SourceType.X,
                        SourceType.REDDIT,
                        SourceType.HACKER_NEWS,
                        SourceType.BLUESKY,
                        SourceType.PRODUCT_HUNT,
                    }
                ),
                allowed_categories=frozenset({CandidateCategory.EARLY_SIGNAL}),
                allowed_signal_statuses=EARLY_SIGNAL_STATUSES,
                required_followup_questions=True,
                task_template=(
                    "Find specific, trackable AI frontier signals in social/community sources. "
                    "Prefer gray rollouts, user-visible changes, researcher hints, and small-circle discussions."
                ),
                focus_topics=("gray_rollouts", "researcher_hints", "community_discussion"),
            ),
            ScoutProfile(
                role=AgentRole.CODE_MODEL_SCOUT,
                display_name="Code & Model Scout",
                source_types=frozenset(
                    {
                        SourceType.GITHUB,
                        SourceType.HUGGING_FACE,
                        SourceType.NPM,
                        SourceType.PYPI,
                        SourceType.DOCKER_HUB,
                    }
                ),
                allowed_categories=frozenset({CandidateCategory.CODE_MODEL, CandidateCategory.EARLY_SIGNAL}),
                allowed_signal_statuses=frozenset(
                    {
                        SignalStatus.CODE_ANOMALY,
                        SignalStatus.SINGLE_SOURCE_SIGNAL,
                        SignalStatus.UNCONFIRMED_LEAK,
                        SignalStatus.GRAY_ROLLOUT_FEEDBACK,
                        SignalStatus.MANUAL_HYPOTHESIS,
                    }
                ),
                required_followup_questions=True,
                task_template=(
                    "Find repo, model, SDK, package, or container anomalies that may signal model, "
                    "agent, or infrastructure changes."
                ),
                focus_topics=("github", "hugging_face", "sdk", "packages", "model_uploads"),
            ),
            ScoutProfile(
                role=AgentRole.RESEARCH_SCOUT,
                display_name="Research Scout",
                source_types=frozenset(
                    {
                        SourceType.ARXIV,
                        SourceType.OPENREVIEW,
                        SourceType.PAPERS_WITH_CODE,
                        SourceType.HUGGING_FACE,
                    }
                ),
                allowed_categories=frozenset({CandidateCategory.RESEARCH, CandidateCategory.EARLY_SIGNAL}),
                allowed_signal_statuses=frozenset(
                    {
                        SignalStatus.RESEARCHER_HINT,
                        SignalStatus.SINGLE_SOURCE_SIGNAL,
                        SignalStatus.NOT_APPLICABLE,
                        SignalStatus.MANUAL_HYPOTHESIS,
                    }
                ),
                required_followup_questions=True,
                task_template=(
                    "Find new papers, benchmarks, reasoning methods, agent methods, and multimodal research signals."
                ),
                focus_topics=("papers", "benchmarks", "reasoning", "agents", "multimodal"),
            ),
            ScoutProfile(
                role=AgentRole.OFFICIAL_SCOUT,
                display_name="Official Scout",
                source_types=frozenset(
                    {
                        SourceType.OFFICIAL_BLOG,
                        SourceType.API_CHANGELOG,
                        SourceType.DOCS,
                    }
                ),
                allowed_categories=frozenset(
                    {CandidateCategory.CONFIRMED_EVENT, CandidateCategory.OFFICIAL_UPDATE}
                ),
                allowed_signal_statuses=frozenset(
                    {
                        SignalStatus.OFFICIAL_CONFIRMATION,
                        SignalStatus.CONFIRMED_FACT,
                        SignalStatus.NOT_APPLICABLE,
                    }
                ),
                required_followup_questions=True,
                required_evidence_strengths=frozenset(
                    {EvidenceStrength.STRONG, EvidenceStrength.OFFICIAL}
                ),
                task_template=(
                    "Find official model, API, pricing, product, policy, benchmark, or technical-report updates."
                ),
                focus_topics=("official_blogs", "api_changelogs", "docs", "model_releases"),
            ),
            ScoutProfile(
                role=AgentRole.FINANCE_SCOUT,
                display_name="Finance Scout",
                source_types=frozenset(
                    {
                        SourceType.INVESTOR_RELATIONS,
                        SourceType.SEC_FILING,
                        SourceType.EARNINGS_CALL,
                        SourceType.SEMIANALYSIS,
                        SourceType.THE_INFORMATION,
                        SourceType.REUTERS,
                        SourceType.BLOOMBERG,
                        SourceType.WSJ,
                        SourceType.CNBC,
                    }
                ),
                allowed_categories=frozenset({CandidateCategory.TECH_FINANCE}),
                allowed_signal_statuses=frozenset(
                    {
                        SignalStatus.NOT_APPLICABLE,
                        SignalStatus.CONFIRMED_FACT,
                        SignalStatus.SINGLE_SOURCE_SIGNAL,
                    }
                ),
                required_followup_questions=True,
                requires_ticker_or_impact=True,
                task_template=(
                    "Find AI infrastructure, semiconductor, capex, revenue, guidance, and supply-chain information "
                    "with ticker or impact-chain relevance."
                ),
                focus_topics=("ai_capex", "semiconductors", "datacenter_revenue", "supply_chain", "tickers"),
            ),
        ]
    )
