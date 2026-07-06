"""Artifact schemas for large or raw payloads."""

from typing import Any

from pydantic import Field, model_validator

from app.domain.base import ArtifactRef, DomainModel, NonEmptyStr
from app.domain.enums import ArtifactKind, ArtifactStorage


class Artifact(DomainModel):
    """A stored payload such as a raw tool response, model output, or report snapshot."""

    run_id: str | None = None
    kind: ArtifactKind
    storage: ArtifactStorage
    uri: str | None = None
    inline_content: str | dict[str, Any] | list[Any] | None = None
    content_type: NonEmptyStr = "application/json"
    sha256: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def ref(self) -> ArtifactRef:
        return ArtifactRef(artifact_id=self.id, kind=self.kind)

    @model_validator(mode="after")
    def validate_storage_location(self) -> "Artifact":
        if self.storage in {ArtifactStorage.INLINE, ArtifactStorage.DATABASE} and self.inline_content is None:
            raise ValueError("inline or database artifacts require inline_content")
        if self.storage in {ArtifactStorage.FILE, ArtifactStorage.OBJECT_STORE} and not self.uri:
            raise ValueError("file or object-store artifacts require uri")
        return self

