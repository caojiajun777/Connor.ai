"""Scout task construction."""

from __future__ import annotations

from typing import Any

from app.domain import AgentRole, RunPhase
from app.harness.decisions import AgentTask
from app.scouts.profiles import ScoutProfileRegistry, create_default_scout_profile_registry


class ScoutTaskFactory:
    """Create AgentTasks from Scout profiles."""

    def __init__(self, profiles: ScoutProfileRegistry | None = None):
        self.profiles = profiles or create_default_scout_profile_registry()

    def create_task(
        self,
        role: AgentRole,
        *,
        objective: str,
        context: dict[str, Any] | None = None,
    ) -> AgentTask:
        profile = self.profiles.require(role)
        return AgentTask(
            agent_role=role,
            phase=RunPhase.SCOUTING,
            task=f"{profile.task_template} Objective: {objective}",
            context={
                "scout_profile": profile.context_payload(),
                "candidate_output_contract": (
                    "Return candidate_drafts. Do not claim facts beyond evidence. "
                    "Use uncertainty and followup_questions."
                ),
                **(context or {}),
            },
        )

    def create_all_tasks(
        self,
        *,
        objective: str,
        context: dict[str, Any] | None = None,
    ) -> list[AgentTask]:
        return [
            self.create_task(profile.role, objective=objective, context=context)
            for profile in sorted(self.profiles.list_profiles(), key=lambda item: item.role.value)
        ]
