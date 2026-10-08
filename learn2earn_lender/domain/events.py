"""The append-only event log record.

Every state change in the application — a resource created, a condition
updated, a loan issued or returned — is written once as an :class:`Event`.
Nothing mutates the log; projections are rebuilt by replaying it (BUILD_PLAN §6).

This is what makes "preserve complete transaction history" and "date/time
logging for every transaction and status change" fall out for free: history
*is* the storage, not a side channel that can drift from it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .errors import ValidationError
from ..validators import strings
from ..validators.dates import parse_datetime


class EventType(str, Enum):
    """Discriminator stored on every event record."""

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
"""Actor recorded for events the application raises on its own, such as seeding."""


@dataclass(frozen=True)
class Event:
    """One immutable fact about the system, as written to the daily log.

    ``payload`` is a plain JSON-compatible mapping. Each event type has a
    documented key set; the service layer builds payloads and the projection
    layer reads them, so the two never disagree about a key name.
    """

    event_id: str
    event_type: EventType
    occurred_at: str
    actor: str = SYSTEM_ACTOR
    payload: Mapping[str, Any] = field(default_factory=dict)
    notes: str = ""

    def __post_init__(self) -> None:
        # Events are built by the service layer as typed objects but arrive
        # back from JSON as plain strings, so normalise to the enum rather
        # than making every caller remember which form it holds.
        object.__setattr__(self, "event_type", EventType.parse(self.event_type))
        object.__setattr__(self, "payload", dict(self.payload))
        # Validate eagerly so a malformed event fails at the call site rather
        # than during a replay, where the cause is far from the symptom.
        parse_datetime(self.occurred_at, "occurred_at")
        if not isinstance(self.payload, Mapping):
            raise ValidationError("event payload must be a mapping")

    @property
    def date_key(self) -> str:
        """The ``YYYY-MM-DD`` bucket this event belongs to."""
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
    """``("2026-02-01", 7)`` -> ``"E-20260201-0007"``.

    Sortable, human-readable, and unique per day. The sequence is supplied by
    the log, which knows how many events that day already holds.
    """
    compact = date_key.replace("-", "")
    return f"E-{compact}-{sequence:04d}"
