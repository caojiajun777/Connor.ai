"""Scout profile registry tests."""

from __future__ import annotations

import pytest

from app.agents.outputs import CandidateDraft
from app.domain import (
    AgentRole,
    CandidateCategory,
    ConfidenceLevel,
    EvidenceStrength,
    RunPhase,
    SignalStatus,
)
from app.scouts import (
    SCOUT_ROLES,
    ScoutProfileError,
    ScoutTaskFactory,
    create_default_scout_profile_registry,
)


def test_default_scout_profile_registry_covers_all_scout_roles() -> None:
    registry = create_default_scout_profile_registry()

    assert {profile.role for profile in registry.list_profiles()} == SCOUT_ROLES

    for role in SCOUT_ROLES:
        profile = registry.require(role)
        payload = profile.context_payload()
        assert payload["role"] == role.value
        assert payload["source_types"]
        assert payload["allowed_categories"]
        assert payload["allowed_signal_statuses"]
        assert "Scout profile constraints" in profile.prompt_extension()


def test_scout_task_factory_embeds_profile_and_output_contract() -> None:
    tasks = ScoutTaskFactory().create_all_tasks(objective="Build today's Connor.ai daily intelligence.")

    assert len(tasks) == 5
    assert {task.agent_role for task in tasks} == SCOUT_ROLES
    assert all(task.phase == RunPhase.SCOUTING for task in tasks)
    assert all("scout_profile" in task.context for task in tasks)
    assert all("candidate_output_contract" in task.context for task in tasks)


def test_finance_profile_rejects_non_finance_candidate() -> None:
    profile = create_default_scout_profile_registry().require(AgentRole.FINANCE_SCOUT)

    with pytest.raises(ScoutProfileError, match="cannot create category"):
        profile.validate_draft(
            CandidateDraft(
                category=CandidateCategory.EARLY_SIGNAL,
                signal_status=SignalStatus.SINGLE_SOURCE_SIGNAL,
                claim_summary="A social rumor says an AI model is being tested.",
                uncertainty=ConfidenceLevel.MEDIUM,
                evidence_strength=EvidenceStrength.MODERATE,
                followup_questions=["Look for independent confirmation."],
            ),
            evidence_items=[],
        )


def test_official_profile_requires_official_or_strong_evidence_strength() -> None:
    profile = create_default_scout_profile_registry().require(AgentRole.OFFICIAL_SCOUT)

    with pytest.raises(ScoutProfileError, match="requires evidence_strength"):
        profile.validate_draft(
            CandidateDraft(
                category=CandidateCategory.CONFIRMED_EVENT,
                signal_status=SignalStatus.OFFICIAL_CONFIRMATION,
                claim_summary="A model launch is officially confirmed.",
                uncertainty=ConfidenceLevel.HIGH,
                evidence_strength=EvidenceStrength.MODERATE,
                followup_questions=["Check API docs for pricing changes."],
            ),
            evidence_items=[],
        )
