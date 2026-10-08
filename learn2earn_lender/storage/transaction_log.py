from __future__ import annotations

from typing import Any, Mapping

from ..domain.errors import StorageError
from ..domain.events import SYSTEM_ACTOR, Event, EventType, format_event_id
from ..validators.dates import date_from_timestamp, now_iso
from . import json_repository
from .paths import DataPaths


class TransactionLog:
    def __init__(self, paths: DataPaths) -> None:
        self._paths = paths
        self._sequences: dict[str, int] = {}

    def append(
        self,
        event_type: EventType | str,
        payload: Mapping[str, Any],
        *,
        actor: str = SYSTEM_ACTOR,
        occurred_at: str | None = None,
        notes: str = "",
    ) -> Event:
        moment = occurred_at or now_iso()
        event = Event(
            event_id=self.next_event_id(moment),
            event_type=event_type,
            occurred_at=moment,
            actor=actor,
            payload=payload,
            notes=notes,
        )
        self.record(event)
        return event

    def record(self, event: Event) -> None:
        date_key = event.date_key
        document = self._read_document(date_key)
        document["events"].append(event.to_dict())
        document["count"] = len(document["events"])
        json_repository.write_json(self._paths.transaction_file(date_key), document)
        self._sequences[date_key] = max(
            self._sequences.get(date_key, 0), _sequence_of(event.event_id)
        )

    def record_many(self, events: list[Event]) -> None:
        by_date: dict[str, list[Event]] = {}
        for event in events:
            by_date.setdefault(event.date_key, []).append(event)
        for date_key, day_events in by_date.items():
            document = self._read_document(date_key)
            document["events"].extend(event.to_dict() for event in day_events)
            document["count"] = len(document["events"])
            json_repository.write_json(self._paths.transaction_file(date_key), document)
            self._sequences[date_key] = max(
                self._sequences.get(date_key, 0),
                *(_sequence_of(event.event_id) for event in day_events),
            )

    def next_event_id(self, occurred_at: str | None = None) -> str:
        date_key = date_from_timestamp(occurred_at or now_iso())
        sequence = self._sequences.get(date_key)
        if sequence is None:
            sequence = len(self._read_document(date_key)["events"])
        sequence += 1
        self._sequences[date_key] = sequence
        return format_event_id(date_key, sequence)

    def read_day(self, date_key: str) -> list[Event]:
        return [Event.from_dict(raw) for raw in self._read_document(date_key)["events"]]

    def read_all(self) -> list[Event]:
        events: list[Event] = []
        for path in json_repository.list_json_files(self._paths.transactions_dir):
            raw = json_repository.read_json(path, default=None)
            if raw is None:
                continue
            for entry in _extract_events(raw, path):
                events.append(Event.from_dict(entry))
        events.sort(key=lambda event: (event.occurred_at, event.event_id))
        return events

    def dates(self) -> list[str]:
        return [
            path.stem
            for path in json_repository.list_json_files(self._paths.transactions_dir)
        ]

    def is_empty(self) -> bool:
        return not self.dates()

    def event_count(self) -> int:
        return sum(len(self._read_document(date_key)["events"]) for date_key in self.dates())

    def _read_document(self, date_key: str) -> dict[str, Any]:
        path = self._paths.transaction_file(date_key)
        raw = json_repository.read_json(path, default=None)
        if raw is None:
            return {"date": date_key, "count": 0, "events": []}
        events = _extract_events(raw, path)
        return {"date": date_key, "count": len(events), "events": events}


def _extract_events(raw: Any, path: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        entries = raw
    elif isinstance(raw, dict):
        entries = raw.get("events")
    else:
        raise StorageError(f"{path} must contain an object or an array of events")

    if not isinstance(entries, list):
        raise StorageError(f"{path} is missing an 'events' array")
    for entry in entries:
        if not isinstance(entry, dict):
            raise StorageError(f"{path} contains a non-object entry in 'events'")
    return entries


def _sequence_of(event_id: str) -> int:
    _, _, tail = str(event_id).rpartition("-")
    try:
        return int(tail)
    except ValueError:
        return 0
