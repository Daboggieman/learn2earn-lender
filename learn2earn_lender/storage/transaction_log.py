"""The append-only daily event log — the application's source of truth.

One file per day, ``transactions/YYYY-MM-DD.json``, holding an array of
events plus enough metadata to make the file self-describing::

    {
      "date": "2026-02-01",
      "count": 3,
      "events": [ { "event_id": "E-20260201-0001", ... } ]
    }

Events are only ever appended. There is no update or delete path, which is
what makes "preserve complete transaction history" a structural property
rather than a discipline the code has to remember.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..domain.errors import StorageError
from ..domain.events import SYSTEM_ACTOR, Event, EventType, format_event_id
from ..validators.dates import date_from_timestamp, now_iso
from . import json_repository
from .paths import DataPaths


class TransactionLog:
    """Reads and appends events for one data directory."""

    def __init__(self, paths: DataPaths) -> None:
        self._paths = paths
        # Per-day append counters. Seeded lazily from the file so that IDs
        # stay unique across separate runs, then incremented in memory so a
        # batch append inside one run does not re-read the file each time.
        self._sequences: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def append(
        self,
        event_type: EventType | str,
        payload: Mapping[str, Any],
        *,
        actor: str = SYSTEM_ACTOR,
        occurred_at: str | None = None,
        notes: str = "",
    ) -> Event:
        """Build an event with a generated ID, write it, and return it."""
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
        """Append an already-built event (used by seeding and import)."""
        date_key = event.date_key
        document = self._read_document(date_key)
        document["events"].append(event.to_dict())
        document["count"] = len(document["events"])
        json_repository.write_json(self._paths.transaction_file(date_key), document)
        # Keep the in-memory counter ahead of what is now on disk.
        self._sequences[date_key] = max(
            self._sequences.get(date_key, 0), _sequence_of(event.event_id)
        )

    def record_many(self, events: list[Event]) -> None:
        """Append several events, grouping writes per day file."""
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
        """Reserve the next ``E-YYYYMMDD-NNNN`` identifier for a timestamp."""
        date_key = date_from_timestamp(occurred_at or now_iso())
        sequence = self._sequences.get(date_key)
        if sequence is None:
            sequence = len(self._read_document(date_key)["events"])
        sequence += 1
        self._sequences[date_key] = sequence
        return format_event_id(date_key, sequence)

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def read_day(self, date_key: str) -> list[Event]:
        """Every event recorded on ``date_key``, in recorded order."""
        return [Event.from_dict(raw) for raw in self._read_document(date_key)["events"]]

    def read_all(self) -> list[Event]:
        """Every event in the log, oldest first.

        Sorted by timestamp then ID rather than by file name alone, so a
        back-dated event (an import, a seed batch) still replays in the
        correct order.
        """
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
        """The ``YYYY-MM-DD`` keys that currently have a log file."""
        return [
            path.stem
            for path in json_repository.list_json_files(self._paths.transactions_dir)
        ]

    def is_empty(self) -> bool:
        return not self.dates()

    def event_count(self) -> int:
        return sum(len(self._read_document(date_key)["events"]) for date_key in self.dates())

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _read_document(self, date_key: str) -> dict[str, Any]:
        """Load a day file, tolerating a missing file as an empty day."""
        path = self._paths.transaction_file(date_key)
        raw = json_repository.read_json(path, default=None)
        if raw is None:
            return {"date": date_key, "count": 0, "events": []}
        events = _extract_events(raw, path)
        return {"date": date_key, "count": len(events), "events": events}


def _extract_events(raw: Any, path: Any) -> list[dict[str, Any]]:
    """Pull the event array out of a day document, checking its shape."""
    if isinstance(raw, list):
        # Tolerate a bare array: hand-written or exported logs stay readable.
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
    """Recover the numeric suffix of ``E-YYYYMMDD-NNNN``; 0 if it does not match."""
    _, _, tail = str(event_id).rpartition("-")
    try:
        return int(tail)
    except ValueError:
        return 0
