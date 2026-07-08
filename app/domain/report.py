"""Report output schemas."""

from datetime import date
from typing import Any

from pydantic import Field, field_validator, model_validator

from app.domain.base import ConnorBaseModel, DomainModel, NonEmptyStr, Score, normalize_unique
from app.domain.enums import CandidateCategory, ReportStatus


class ReportItem(ConnorBaseModel):
    """A structured item rendered in the daily report."""

    item_id: NonEmptyStr
    title: NonEmptyStr
    category: CandidateCategory
    status_label: NonEmptyStr
    core_information: NonEmptyStr
    why_it_matters: NonEmptyStr
    potential_impact: str | None = None
    key_data: list[str] = Field(default_factory=list)
    tickers: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    cluster_ids: list[str] = Field(default_factory=list)
    followup_points: list[str] = Field(default_factory=list)
    uncertainty_label: str | None = None

    @field_validator("evidence_ids", "cluster_ids", "tickers")
    @classmethod
    def values_must_be_unique(cls, value: list[str]) -> list[str]:
        return normalize_unique(value)

    @model_validator(mode="after")
    def validate_report_item_rules(self) -> "ReportItem":
        if not self.evidence_ids:
            raise ValueError("report items require evidence_ids")
        if not self.cluster_ids:
            raise ValueError("report items require cluster_ids")
        if self.category == CandidateCategory.EARLY_SIGNAL and not self.uncertainty_label:
            raise ValueError("early-signal report items require uncertainty_label")
        if self.category == CandidateCategory.TECH_FINANCE and not (
            self.tickers or self.potential_impact
        ):
            raise ValueError("tech-finance items require tickers or potential_impact")
        return self


class ReportSection(ConnorBaseModel):
    """A named report section."""

    section_id: NonEmptyStr
    title: NonEmptyStr
    items: list[ReportItem] = Field(default_factory=list)


class EvidenceMapEntry(ConnorBaseModel):
    """Mapping between report output and supporting lineage."""

    report_item_id: NonEmptyStr
    evidence_ids: list[str] = Field(default_factory=list)
    cluster_ids: list[str] = Field(default_factory=list)
    trace_event_ids: list[str] = Field(default_factory=list)


class WatchlistUpdate(ConnorBaseModel):
    """Watchlist information included in the final report artifact."""

    watchlist_id: NonEmptyStr
    topic: NonEmptyStr
    current_status: NonEmptyStr
    new_developments: list[str] = Field(default_factory=list)
    next_watch: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class DailyReport(DomainModel):
    """Final daily report artifact and structured dashboard data."""

    run_id: NonEmptyStr
    report_date: date
    title: NonEmptyStr = "Connor.ai Daily Intelligence"
    status: ReportStatus = ReportStatus.DRAFT
    full_markdown: str | None = None
    full_json: dict[str, Any] = Field(default_factory=dict)
    sections: list[ReportSection] = Field(default_factory=list)
    evidence_map: list[EvidenceMapEntry] = Field(default_factory=list)
    watchlist_updates: list[WatchlistUpdate] = Field(default_factory=list)
    trace_timeline_ids: list[str] = Field(default_factory=list)
    review_result_ids: list[str] = Field(default_factory=list)
    quality_score: Score | None = None
    overview_judgments: list[str] = Field(default_factory=list)
    tomorrow_focus: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_report_consistency(self) -> "DailyReport":
        item_ids = {item.item_id for section in self.sections for item in section.items}
        evidence_map_ids = {entry.report_item_id for entry in self.evidence_map}

        missing_map_entries = item_ids - evidence_map_ids
        if missing_map_entries:
            raise ValueError(f"report items missing evidence_map entries: {missing_map_entries}")

        if self.full_json:
            section_ids = [section.section_id for section in self.sections]
            json_section_ids = [
                section.get("section_id")
                for section in self.full_json.get("sections", [])
                if isinstance(section, dict)
            ]
            if json_section_ids and json_section_ids != section_ids:
                raise ValueError("full_json sections must align with sections")

        if self.status == ReportStatus.FINAL:
            if not self.full_markdown:
                raise ValueError("final reports require full_markdown")
            if not self.sections:
                raise ValueError("final reports require sections")
            if not self.trace_timeline_ids:
                raise ValueError("final reports require trace_timeline_ids")

        return self

