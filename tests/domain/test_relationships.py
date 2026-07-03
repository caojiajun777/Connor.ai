"""Relationship and lineage tests for Connor.ai schemas."""

import pytest
from pydantic import ValidationError

from app.domain import (
    ArchiveReason,
    ArchivedSignal,
    DailyReport,
    EvidenceItem,
    IntelligenceThread,
)
from tests.domain.fixtures import (
    BASE_TIME,
    RUN_ID,
    daily_report_fixture,
    early_signal_bundle,
    tool_envelope_fixture,
)


def test_candidate_cluster_evaluation_lineage_is_preserved() -> None:
    bundle = early_signal_bundle()
    evidence = bundle["evidence"]
    candidate = bundle["candidate"]
    cluster = bundle["cluster"]
    evaluation = bundle["evaluation"]

    evidence_ids = {item.id for item in evidence}
    assert set(candidate.evidence_ids).issubset(evidence_ids)
    assert candidate.id in cluster.candidate_ids
    assert set(cluster.evidence_ids).issubset(evidence_ids)
    assert evaluation.cluster_id == cluster.id


def test_daily_report_items_have_evidence_map_entries() -> None:
    report = daily_report_fixture()
    assert isinstance(report, DailyReport)

    item_ids = {item.item_id for section in report.sections for item in section.items}
    mapped_ids = {entry.report_item_id for entry in report.evidence_map}
    assert item_ids == mapped_ids


def test_report_rejects_missing_evidence_map_entry() -> None:
    report = daily_report_fixture()
    with pytest.raises(ValidationError):
        DailyReport(
            **{
                **report.model_dump(),
                "id": "report_missing_map",
                "evidence_map": report.evidence_map[:-1],
            }
        )


def test_archive_requires_lineage() -> None:
    with pytest.raises(ValidationError):
        ArchivedSignal(
            id="arch_without_source",
            run_id=RUN_ID,
            archive_reason=ArchiveReason.NO_NEW_SIGNAL,
            archived_at=BASE_TIME,
            final_state="No lineage should fail.",
        )


def test_thread_timeline_links_archive_watch_and_cluster() -> None:
    thread = early_signal_bundle()["thread"]
    assert isinstance(thread, IntelligenceThread)
    assert thread.linked_cluster_ids
    assert thread.linked_watchlist_ids
    assert thread.linked_archive_ids
    assert all(entry.cluster_id or entry.watchlist_id or entry.archive_id for entry in thread.timeline)


def test_tool_envelope_normalizes_to_evidence_items() -> None:
    envelope = tool_envelope_fixture()
    evidence = envelope.to_evidence_items(
        run_id=RUN_ID,
        evidence_id_factory=lambda index, item: f"ev_tool_{index}_{item.raw_hash}",
    )

    assert len(evidence) == 1
    assert isinstance(evidence[0], EvidenceItem)
    assert evidence[0].id == "ev_tool_0_sha256:tool-item"
    assert evidence[0].source_type == envelope.source_type
    assert evidence[0].retrieved_at == envelope.retrieved_at

