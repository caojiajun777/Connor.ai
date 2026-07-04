"""Generic domain repository helpers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

DomainT = TypeVar("DomainT", bound=BaseModel)
RecordT = TypeVar("RecordT")


def enum_value(value: Any) -> Any:
    """Return a JSON/database-friendly enum value."""

    return getattr(value, "value", value)


def payload_from_domain(obj: BaseModel) -> dict[str, Any]:
    """Serialize a Phase 1 domain object for payload storage."""

    return obj.model_dump(mode="json")


class DomainRepository(Generic[DomainT, RecordT]):
    """Base repository for storing complete domain payloads plus query columns."""

    domain_model: type[DomainT]
    record_model: type[RecordT]

    def __init__(self, session: Session):
        self.session = session

    def add(self, obj: DomainT) -> DomainT:
        record = self.to_record(obj)
        self.session.merge(record)
        return obj

    def add_many(self, objects: Sequence[DomainT]) -> list[DomainT]:
        for obj in objects:
            self.add(obj)
        return list(objects)

    def get(self, object_id: str) -> DomainT | None:
        record = self.session.get(self.record_model, object_id)
        if record is None:
            return None
        return self.to_domain(record)

    def require(self, object_id: str) -> DomainT:
        obj = self.get(object_id)
        if obj is None:
            raise LookupError(f"{self.record_model.__name__} not found: {object_id}")
        return obj

    def list_by_run(self, run_id: str) -> list[DomainT]:
        stmt = (
            select(self.record_model)
            .where(self.record_model.run_id == run_id)
            .order_by(self.record_model.created_at)
        )
        return [self.to_domain(record) for record in self.session.scalars(stmt)]

    def list_all(self) -> list[DomainT]:
        stmt = select(self.record_model).order_by(self.record_model.created_at)
        return [self.to_domain(record) for record in self.session.scalars(stmt)]

    def delete(self, object_id: str) -> bool:
        record = self.session.get(self.record_model, object_id)
        if record is None:
            return False
        self.session.delete(record)
        return True

    def to_record(self, obj: DomainT) -> RecordT:
        raise NotImplementedError

    def to_domain(self, record: RecordT) -> DomainT:
        return self.domain_model.model_validate(record.payload)

    @staticmethod
    def _common_values(obj: BaseModel) -> dict[str, Any]:
        return {
            "id": obj.id,
            "schema_version": obj.schema_version,
            "created_at": obj.created_at,
            "updated_at": obj.updated_at,
            "payload": payload_from_domain(obj),
        }
