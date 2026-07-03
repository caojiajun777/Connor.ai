"""Evidence schemas."""

from typing import Any

from pydantic import Field, model_validator

from app.domain.base import ArtifactRef, AwareDatetime, DomainModel, NonEmptyStr, utc_now
from app.domain.enums import EvidenceStrength, SourceAccessLevel, SourceType


class EvidenceItem(DomainModel):
    """A normalized source item that can support candidates, clusters, and report items."""

    run_id: NonEmptyStr
    source_type: SourceType
    source_name: str | None = None
    access_level: SourceAccessLevel = SourceAccessLevel.PUBLIC
    strength: EvidenceStrength = EvidenceStrength.UNKNOWN
    url: str | None = None
    title: NonEmptyStr
    author: str | None = None
    published_at: AwareDatetime | None = None
    retrieved_at: AwareDatetime = Field(default_factory=utc_now)
    snippet: NonEmptyStr
    raw_ref: str | None = None
    raw_artifact_ref: ArtifactRef | None = None
    raw_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_source_pointer(self) -> "EvidenceItem":
        if not any([self.url, self.raw_ref, self.raw_artifact_ref]):
            raise ValueError("evidence requires url, raw_ref, or raw_artifact_ref")
        return self

