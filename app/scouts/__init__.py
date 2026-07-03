"""Scout role profiles and task templates."""

from app.scouts.profiles import (
    SCOUT_ROLES,
    ScoutProfile,
    ScoutProfileError,
    ScoutProfileRegistry,
    create_default_scout_profile_registry,
)


def __getattr__(name: str):
    if name == "ScoutTaskFactory":
        from app.scouts.tasks import ScoutTaskFactory

        return ScoutTaskFactory
    raise AttributeError(name)

__all__ = [
    "SCOUT_ROLES",
    "ScoutProfile",
    "ScoutProfileError",
    "ScoutProfileRegistry",
    "ScoutTaskFactory",
    "create_default_scout_profile_registry",
]
