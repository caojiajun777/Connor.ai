"""Artifact service tests."""

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain import ArtifactKind, ArtifactStorage
from app.repositories import RunRepository
from app.services import ArtifactService
from tests.domain.fixtures import run_state_fixture


def test_artifact_service_stores_and_reads_inline_payload(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    service = ArtifactService(db_session, inline_max_bytes=10_000)

    artifact = service.store_payload(
        run_id="run_2026_07_03",
        kind=ArtifactKind.RAW_TOOL_RESPONSE,
        payload={"items": [{"title": "OpenAI wrapper commit"}]},
    )
    db_session.commit()

    assert artifact.storage == ArtifactStorage.INLINE
    assert artifact.sha256 is not None
    assert artifact.size_bytes is not None
    assert service.read_payload(artifact.id) == {"items": [{"title": "OpenAI wrapper commit"}]}


def test_artifact_service_writes_large_or_binary_payload_to_file(db_session, tmp_path) -> None:
    RunRepository(db_session).add(run_state_fixture())
    service = ArtifactService(db_session, artifact_root=tmp_path, inline_max_bytes=4)

    payload = b"binary raw snapshot"
    artifact = service.store_payload(
        run_id="run_2026_07_03",
        kind=ArtifactKind.RAW_PAGE_SNAPSHOT,
        payload=payload,
    )
    db_session.commit()

    assert artifact.storage == ArtifactStorage.FILE
    assert artifact.uri is not None
    assert service.read_payload(artifact.id) == payload
    assert artifact.sha256 == f"sha256:{hashlib.sha256(payload).hexdigest()}"


def test_artifact_service_can_store_database_payload(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    service = ArtifactService(db_session)

    artifact = service.store_payload(
        run_id="run_2026_07_03",
        kind=ArtifactKind.NORMALIZED_PAYLOAD,
        payload={"normalized": True},
        storage=ArtifactStorage.DATABASE,
    )
    db_session.commit()

    assert artifact.storage == ArtifactStorage.DATABASE
    assert service.read_payload(artifact.id) == {"normalized": True}


def test_artifact_service_cleanup_removes_orphan_and_tmp_files(db_session, tmp_path) -> None:
    RunRepository(db_session).add(run_state_fixture())
    service = ArtifactService(db_session, artifact_root=tmp_path, inline_max_bytes=4)

    artifact = service.store_payload(
        run_id="run_2026_07_03",
        kind=ArtifactKind.RAW_PAGE_SNAPSHOT,
        payload=b"binary raw snapshot",
    )
    db_session.flush()
    artifact_path = Path(artifact.uri)
    orphan_path = artifact_path.with_name("orphan_payload.bin")
    tmp_path_leftover = artifact_path.with_name("unfinished_payload.bin.tmp")
    orphan_path.write_bytes(b"orphan")
    tmp_path_leftover.write_bytes(b"unfinished")

    removed = service.cleanup_orphan_artifacts()

    assert removed == 2
    assert artifact_path.exists()
    assert not orphan_path.exists()
    assert not tmp_path_leftover.exists()


def test_artifact_service_rejects_hidden_reasoning_keys(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    service = ArtifactService(db_session)

    with pytest.raises(ValueError):
        service.store_payload(
            run_id="run_2026_07_03",
            kind=ArtifactKind.MODEL_OUTPUT,
            payload={"chain_of_thought": "do not store"},
        )
