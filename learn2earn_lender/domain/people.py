"""Borrowers.

Two kinds of people can borrow: **Fellows** (accepted students, members of a
cohort) and **Piscine candidates** (prospective Fellows in a trial period).
They share one record shape and differ by ``type`` and by the group they
belong to, so a candidate who passes trials is promoted by changing two
fields rather than by being re-created.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .errors import ValidationError
from ..validators import strings
from ..validators.ids import next_sequential_id, validate_id


class PersonType(str, Enum):
    FELLOW = "fellow"
    PISCINE = "piscine"

    @classmethod
    def parse(cls, value: object) -> "PersonType":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            raise ValidationError(
                f"unknown borrower type {value!r}: expected 'fellow' or 'piscine'"
            ) from exc


class PersonStatus(str, Enum):
    """``active`` borrowers may borrow; everything else is blocked."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    REMOVED = "removed"

    @classmethod
    def parse(cls, value: object) -> "PersonStatus":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            raise ValidationError(f"unknown borrower status {value!r}") from exc


@dataclass
class Person:
    """A Fellow or a Piscine candidate."""

    id: str
    name: str
    type: PersonType
    group_id: str
    status: PersonStatus = PersonStatus.ACTIVE
    created_at: str = ""
    updated_at: str = ""
    notes: str = ""

    @property
    def is_fellow(self) -> bool:
        return self.type is PersonType.FELLOW

    @property
    def is_piscine(self) -> bool:
        return self.type is PersonType.PISCINE

    @property
    def can_borrow(self) -> bool:
        """Only active borrowers may take equipment (BUILD_PLAN §9.5)."""
        return self.status is PersonStatus.ACTIVE

    def require_can_borrow(self) -> None:
        if not self.can_borrow:
            raise ValidationError(
                f"borrower {self.id} ({self.name}) is {self.status.value} "
                "and cannot borrow equipment"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "group_id": self.group_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Person":
        if not isinstance(data, dict):
            raise ValidationError(
                f"person record must be an object, got {type(data).__name__}"
            )
        for key in ("id", "name", "type"):
            if not data.get(key):
                raise ValidationError(f"person record is missing {key}")
        return cls(
            id=validate_id(data["id"], "person id"),
            name=strings.normalise_name(data["name"], "person name"),
            type=PersonType.parse(data["type"]),
            group_id=strings.require_non_empty(data.get("group_id", ""), "group_id"),
            status=PersonStatus.parse(data.get("status", PersonStatus.ACTIVE.value)),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            notes=str(data.get("notes", "")),
        )


def make_person_id(existing: list[str], person_type: PersonType) -> str:
    """Fellows are ``F###``; Piscine candidates are ``P###``.

    Distinct prefixes keep the two populations readable in reports and make a
    mis-typed borrower ID fail loudly instead of silently borrowing as the
    wrong person.
    """
    prefix = "F" if person_type is PersonType.FELLOW else "P"
    return next_sequential_id(prefix, existing)
