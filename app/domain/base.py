"""Base primitives and validation helpers for Connor.ai domain schemas."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import ArtifactKind, ObjectType

SCHEMA_VERSION = "1.0"

FORBIDDEN_REASONING_KEYS = {
    "chain_of_thought",
    "cot",
    "full_reasoning",
    "hidden_reasoning",
    "private_reasoning",
}


def utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""

    return datetime.now(timezone.utc)


def ensure_aware_datetime(value: datetime) -> datetime:
    """Require timezone-aware datetimes throughout the domain layer."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


AwareDatetime = Annotated[datetime, AfterValidator(ensure_aware_datetime)]
NonEmptyStr = Annotated[str, Field(min_length=1)]
Score = Annotated[float, Field(ge=0, le=10)]
Probability = Annotated[float, Field(ge=0, le=1)]


def normalize_unique(values: Iterable[str]) -> list[str]:
    """Keep order while removing duplicate strings."""

    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def reject_forbidden_reasoning_keys(value: Any, path: str = "metadata") -> None:
    """Reject metadata keys that imply storing hidden chain-of-thought."""

    if isinstance(value, dict):
        for key, nested_value in value.items():
            normalized_key = str(key).strip().lower()
            if normalized_key in FORBIDDEN_REASONING_KEYS:
                raise ValueError(f"{path}.{key} is not allowed; store reasoning summaries only")
            reject_forbidden_reasoning_keys(nested_value, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_forbidden_reasoning_keys(item, f"{path}[{index}]")


class ConnorBaseModel(BaseModel):
    """Strict base model for all Connor.ai domain objects."""

    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
        use_enum_values=False,
        validate_assignment=True,
    )

    @field_validator("metadata", check_fields=False)
    @classmethod
    def metadata_must_not_store_hidden_reasoning(cls, value: dict[str, Any]) -> dict[str, Any]:
        reject_forbidden_reasoning_keys(value)
        return value


class DomainModel(ConnorBaseModel):
    """Base for persisted or traceable domain entities."""

    id: NonEmptyStr
    schema_version: str = Field(default=SCHEMA_VERSION)
    created_at: AwareDatetime = Field(default_factory=utc_now)
    updated_at: AwareDatetime | None = None

    @field_validator("updated_at")
    @classmethod
    def updated_at_must_be_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        return ensure_aware_datetime(value)


class ObjectRef(ConnorBaseModel):
    """Reference to another domain object without embedding it."""

    object_type: ObjectType
    object_id: NonEmptyStr


class ArtifactRef(ConnorBaseModel):
    """Reference to an artifact payload stored outside a primary object."""

    artifact_id: NonEmptyStr
    kind: ArtifactKind

