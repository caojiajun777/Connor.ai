"""Artifact storage service."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.ids import IdPrefix, random_id
from app.domain import Artifact, ArtifactKind, ArtifactStorage
from app.domain.base import reject_forbidden_reasoning_keys, utc_now
from app.repositories import ArtifactRepository


@dataclass(frozen=True)
class SerializedArtifactPayload:
    """A prepared artifact payload ready for hashing and storage."""

    content: bytes
    inline_content: str | dict[str, Any] | list[Any] | None
    content_type: str
    suffix: str


class ArtifactService:
    """Create, persist, and read artifacts with consistent hashing and storage rules."""

    def __init__(
        self,
        session: Session,
        *,
        artifact_root: str | Path | None = None,
        inline_max_bytes: int | None = None,
    ):
        settings = get_settings()
        self.session = session
        self.repository = ArtifactRepository(session)
        self.artifact_root = Path(artifact_root or settings.artifact_root)
        self.inline_max_bytes = inline_max_bytes or settings.artifact_inline_max_bytes

    def store_payload(
        self,
        *,
        kind: ArtifactKind,
        payload: str | bytes | dict[str, Any] | list[Any],
        run_id: str | None = None,
        artifact_id: str | None = None,
        content_type: str | None = None,
        storage: ArtifactStorage | None = None,
        metadata: dict[str, Any] | None = None,
        allow_reasoning_keys: bool = False,
    ) -> Artifact:
        """Store a payload as an Artifact and return the persisted domain object."""

        if not allow_reasoning_keys and isinstance(payload, (dict, list)):
            reject_forbidden_reasoning_keys(payload, path="payload")

        serialized = self._serialize_payload(payload, content_type=content_type)
        sha256 = hashlib.sha256(serialized.content).hexdigest()
        artifact_id = artifact_id or self._new_artifact_id(kind, sha256)
        storage = storage or self._choose_storage(serialized)

        uri: str | None = None
        inline_content: str | dict[str, Any] | list[Any] | None = None

        if storage == ArtifactStorage.FILE:
            uri = str(self._write_file_artifact(run_id, artifact_id, serialized))
        elif storage in {ArtifactStorage.INLINE, ArtifactStorage.DATABASE}:
            inline_content = serialized.inline_content
            if inline_content is None:
                inline_content = serialized.content.decode("utf-8")
        elif storage == ArtifactStorage.OBJECT_STORE:
            raise NotImplementedError("object-store artifact storage is reserved for a later phase")

        artifact = Artifact(
            id=artifact_id,
            run_id=run_id,
            kind=kind,
            storage=storage,
            uri=uri,
            inline_content=inline_content,
            content_type=serialized.content_type,
            sha256=f"sha256:{sha256}",
            size_bytes=len(serialized.content),
            metadata=metadata or {},
            created_at=utc_now(),
        )
        try:
            self.repository.add(artifact)
        except Exception:
            if storage == ArtifactStorage.FILE and uri is not None:
                Path(uri).unlink(missing_ok=True)
            raise
        return artifact

    def get(self, artifact_id: str) -> Artifact:
        """Return an Artifact by id."""

        return self.repository.require(artifact_id)

    def read_payload(self, artifact_id: str) -> str | bytes | dict[str, Any] | list[Any] | None:
        """Read an artifact payload from inline/database/file storage."""

        artifact = self.get(artifact_id)
        if artifact.storage in {ArtifactStorage.INLINE, ArtifactStorage.DATABASE}:
            return artifact.inline_content

        if artifact.storage == ArtifactStorage.FILE:
            if artifact.uri is None:
                raise ValueError(f"file artifact {artifact.id} has no uri")
            path = Path(artifact.uri)
            data = path.read_bytes()
            if artifact.content_type == "application/json":
                return json.loads(data.decode("utf-8"))
            if artifact.content_type.startswith("text/"):
                return data.decode("utf-8")
            return data

        raise NotImplementedError("object-store artifact reading is reserved for a later phase")

    def _choose_storage(self, serialized: SerializedArtifactPayload) -> ArtifactStorage:
        if len(serialized.content) <= self.inline_max_bytes and serialized.inline_content is not None:
            return ArtifactStorage.INLINE
        return ArtifactStorage.FILE

    def _write_file_artifact(
        self,
        run_id: str | None,
        artifact_id: str,
        serialized: SerializedArtifactPayload,
    ) -> Path:
        safe_run_id = self._safe_path_part(run_id or "global")
        safe_artifact_id = self._safe_path_part(artifact_id)
        directory = self.artifact_root / safe_run_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{safe_artifact_id}{serialized.suffix}"
        # Write to a temp file first, then atomically rename to the final path.
        # This prevents partially-written files if the process crashes mid-write.
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_bytes(serialized.content)
        tmp_path.replace(path)
        return path.resolve()

    def cleanup_orphan_artifacts(self) -> int:
        """Remove artifact files on disk that have no matching database record.

        Returns the number of orphan files removed.
        """
        removed = 0
        if not self.artifact_root.exists():
            return 0
        for run_dir in self.artifact_root.iterdir():
            if not run_dir.is_dir():
                continue
            for file_path in run_dir.iterdir():
                if not file_path.is_file():
                    continue
                # Extract the artifact ID from the filename (suffix may be .json, .txt, .bin, or .tmp).
                artifact_id = file_path.stem
                if file_path.suffix == ".tmp":
                    # Temp files are always removable because the write never completed.
                    file_path.unlink(missing_ok=True)
                    removed += 1
                    continue
                existing = self.repository.get(artifact_id)
                if existing is None:
                    file_path.unlink(missing_ok=True)
                    removed += 1
        return removed

    @staticmethod
    def _serialize_payload(
        payload: str | bytes | dict[str, Any] | list[Any],
        *,
        content_type: str | None,
    ) -> SerializedArtifactPayload:
        if isinstance(payload, bytes):
            return SerializedArtifactPayload(
                content=payload,
                inline_content=None,
                content_type=content_type or "application/octet-stream",
                suffix=".bin",
            )

        if isinstance(payload, (dict, list)):
            json_safe_payload = ArtifactService._json_safe(payload)
            content = json.dumps(
                json_safe_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
            return SerializedArtifactPayload(
                content=content,
                inline_content=json_safe_payload,
                content_type=content_type or "application/json",
                suffix=".json",
            )

        content = payload.encode("utf-8")
        selected_content_type = content_type or "text/plain"
        suffix = ".json" if selected_content_type == "application/json" else ".txt"
        return SerializedArtifactPayload(
            content=content,
            inline_content=payload,
            content_type=selected_content_type,
            suffix=suffix,
        )

    @staticmethod
    def _new_artifact_id(kind: ArtifactKind, sha256: str) -> str:
        return random_id(IdPrefix.ARTIFACT, parts=[kind.value, sha256[:16]], length=16)

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, dict):
            return {str(key): ArtifactService._json_safe(nested) for key, nested in value.items()}
        if isinstance(value, list):
            return [ArtifactService._json_safe(item) for item in value]
        if isinstance(value, tuple):
            return [ArtifactService._json_safe(item) for item in value]
        return value

    @staticmethod
    def _safe_path_part(value: str) -> str:
        safe = "".join(character if character.isalnum() or character in {"-", "_"} else "_" for character in value)
        if not safe:
            raise ValueError("artifact path component cannot be empty")
        return safe
