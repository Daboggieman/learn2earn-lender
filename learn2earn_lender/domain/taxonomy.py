from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .errors import ValidationError
from ..validators import strings
from ..validators.ids import next_sequential_id, validate_id


class TaxonomyType(str, Enum):
    CATEGORY = "category"
    SUBCATEGORY = "subcategory"

    @classmethod
    def parse(cls, value: object) -> "TaxonomyType":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            raise ValidationError(f"unknown taxonomy type {value!r}") from exc


class TaxonomyStatus(str, Enum):
    ACTIVE = "active"
    REMOVED = "removed"

    @classmethod
    def parse(cls, value: object) -> "TaxonomyStatus":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            raise ValidationError(f"unknown taxonomy status {value!r}") from exc


@dataclass
class TaxonomyNode:
    id: str
    name: str
    type: TaxonomyType
    parent_id: str | None = None
    status: TaxonomyStatus = TaxonomyStatus.ACTIVE
    created_at: str = ""
    updated_at: str = ""

    @property
    def is_category(self) -> bool:
        return self.type is TaxonomyType.CATEGORY

    @property
    def is_subcategory(self) -> bool:
        return self.type is TaxonomyType.SUBCATEGORY

    @property
    def is_active(self) -> bool:
        return self.status is TaxonomyStatus.ACTIVE

    def check_shape(self) -> None:
        if self.is_category and self.parent_id is not None:
            raise ValidationError(
                f"category {self.id} must not have a parent_id (got {self.parent_id!r})"
            )
        if self.is_subcategory and not self.parent_id:
            raise ValidationError(f"subcategory {self.id} requires a parent_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "parent_id": self.parent_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaxonomyNode":
        if not isinstance(data, dict):
            raise ValidationError(
                f"taxonomy record must be an object, got {type(data).__name__}"
            )
        for key in ("id", "name", "type"):
            if not data.get(key):
                raise ValidationError(f"taxonomy record is missing {key}")

        node_type = TaxonomyType.parse(data["type"])
        parent_id = data.get("parent_id")
        parent_id = str(parent_id).strip() if parent_id else None

        node = cls(
            id=validate_id(data["id"], "taxonomy id"),
            name=strings.normalise_name(data["name"], "taxonomy name"),
            type=node_type,
            parent_id=parent_id,
            status=TaxonomyStatus.parse(data.get("status", TaxonomyStatus.ACTIVE.value)),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )
        node.check_shape()
        return node


def make_category_id(existing: list[str]) -> str:
    return next_sequential_id("C", existing)


def make_subcategory_id(existing: list[str]) -> str:
    return next_sequential_id("S", existing)
