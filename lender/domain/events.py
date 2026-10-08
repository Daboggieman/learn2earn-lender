from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .errors import ValidationError
from ..validators import strings
from ..validators.dates import parse_datetime


class EventType(str, Enum):
    RESOURCE_CREATED = "resource.created"
    RESOURCE_UPDATED = "resource.updated"
    RESOURCE_REMOVED = "resource.removed"
    RESOURCE_CONDITION_CHANGED = "resource.condition_changed"

    TAXONOMY_CREATED = "taxonomy.created"
    TAXONOMY_UPDATED = "taxonomy.updated"
    TAXONOMY_REMOVED = "taxonomy.removed"

    GROUP_CREATED = "group.created"
    GROUP_UPDATED = "group.updated"

    PERSON_CREATED = "person.created"
    PERSON_UPDATED = "person.updated"

    LOAN_CHECKED_OUT = "loan.checked_out"
    LOAN_RETURNED = "loan.returned"

    @classmethod
    def parse(cls, value: object) -> "EventType":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            raise ValidationError(f"unknown event type {value!r}") from exc


SYSTEM_ACTOR = "system"


@dataclass(frozen=True)
class Event:
    event_id: str
    event_type: EventType
    occurred_at: str
    actor: str = SYSTEM_ACTOR
    payload: Mapping[str, Any] = field(default_factory=dict)
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_type", EventType.parse(self.event_type))
        object.__setattr__(self, "payload", dict(self.payload))
        parse_datetime(self.occurred_at, "occurred_at")
        if not isinstance(self.payload, Mapping):
            raise ValidationError("event payload must be a mapping")

    @property
    def date_key(self) -> str:
        return parse_datetime(self.occurred_at, "occurred_at").strftime("%Y-%m-%d")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "occurred_at": self.occurred_at,
            "actor": self.actor,
            "payload": dict(self.payload),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        if not isinstance(data, dict):
            raise ValidationError(
                f"event record must be an object, got {type(data).__name__}"
            )
        for key in ("event_id", "event_type", "occurred_at"):
            if not data.get(key):
                raise ValidationError(f"event record is missing {key}")
        return cls(
            event_id=strings.require_non_empty(data["event_id"], "event_id"),
            event_type=EventType.parse(data["event_type"]),
            occurred_at=str(data["occurred_at"]),
            actor=str(data.get("actor") or SYSTEM_ACTOR),
            payload=dict(data.get("payload") or {}),
            notes=str(data.get("notes", "")),
        )


def format_event_id(date_key: str, sequence: int) -> str:
    compact = date_key.replace("-", "")
    return f"E-{compact}-{sequence:04d}"
