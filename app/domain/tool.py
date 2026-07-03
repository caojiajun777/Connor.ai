"""Tool envelope schemas and evidence normalization."""

from collections.abc import Callable
from typing import Any

from pydantic import Field

from app.domain.base import ArtifactRef, AwareDatetime, ConnorBaseModel, NonEmptyStr, utc_now
from app.domain.enums import EvidenceStrength, SourceAccessLevel, SourceType
from app.domain.evidence import EvidenceItem


class ToolError(ConnorBaseModel):
    """A normalized tool error entry."""

    code: NonEmptyStr
    message: NonEmptyStr
    retryable: bool = False


class ToolEnvelopeItem(ConnorBaseModel):
    """One normalized result item returned by a tool."""

    title: NonEmptyStr
    url: str | None = None
    author: str | None = None
    published_at: AwareDatetime | None = None
    snippet: NonEmptyStr
    raw_ref: str | None = None
    raw_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolEnvelope(ConnorBaseModel):
    """Standard return envelope for every Connor.ai tool."""

    tool_name: NonEmptyStr
    source_type: SourceType
    query: NonEmptyStr
    retrieved_at: AwareDatetime = Field(default_factory=utc_now)
    items: list[ToolEnvelopeItem] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)
    rate_limit: dict[str, Any] = Field(default_factory=dict)
    raw_artifact_ref: ArtifactRef | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_evidence_items(
        self,
        *,
        run_id: str,
        evidence_id_factory: Callable[[int, ToolEnvelopeItem], str],
        source_name: str | None = None,
        access_level: SourceAccessLevel = SourceAccessLevel.PUBLIC,
        strength: EvidenceStrength = EvidenceStrength.UNKNOWN,
    ) -> list[EvidenceItem]:
        """Normalize tool result items into EvidenceItem objects."""

        evidence_items: list[EvidenceItem] = []
        for index, item in enumerate(self.items):
            evidence_items.append(
                EvidenceItem(
                    id=evidence_id_factory(index, item),
                    run_id=run_id,
                    source_type=self.source_type,
                    source_name=source_name or self.tool_name,
                    access_level=access_level,
                    strength=strength,
                    url=item.url,
                    title=item.title,
                    author=item.author,
                    published_at=item.published_at,
                    retrieved_at=self.retrieved_at,
                    snippet=item.snippet,
                    raw_ref=item.raw_ref,
                    raw_artifact_ref=self.raw_artifact_ref,
                    raw_hash=item.raw_hash,
                    metadata=item.metadata,
                )
            )
        return evidence_items

