from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .errors import ValidationError
from ..validators import strings
from ..validators.ids import next_sequential_id, validate_id


class GroupType(str, Enum):
    COHORT = "cohort"
    TRIAL = "trial"

    @classmethod
    def parse(cls, value: object) -> "GroupType":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            raise ValidationError(
                f"unknown group type {value!r}: expected 'cohort' or 'trial'"
            ) from exc


class GroupStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    REMOVED = "removed"

    @classmethod
    def parse(cls, value: object) -> "GroupStatus":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            raise ValidationError(f"unknown group status {value!r}") from exc


@dataclass
class Group:
    id: str
    name: str
    type: GroupType
    status: GroupStatus = GroupStatus.ACTIVE
    created_at: str = ""
    updated_at: str = ""

    @property
    def is_cohort(self) -> bool:
        return self.type is GroupType.COHORT

    @property
    def is_trial(self) -> bool:
        return self.type is GroupType.TRIAL

    @property
    def is_active(self) -> bool:
        return self.status is GroupStatus.ACTIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Group":
        if not isinstance(data, dict):
            raise ValidationError(
                f"group record must be an object, got {type(data).__name__}"
            )
        for key in ("id", "name", "type"):
            if not data.get(key):
                raise ValidationError(f"group record is missing {key}")
        return cls(
            id=validate_id(data["id"], "group id"),
            name=strings.normalise_name(data["name"], "group name"),
            type=GroupType.parse(data["type"]),
            status=GroupStatus.parse(data.get("status", GroupStatus.ACTIVE.value)),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )


def make_group_id(existing: list[str]) -> str:
    return next_sequential_id("G", existing)
