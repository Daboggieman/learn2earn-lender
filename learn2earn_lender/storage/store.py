from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from ..domain.events import SYSTEM_ACTOR, Event, EventType
from ..validators.dates import now_iso
from .paths import DataPaths
from .projections import State, apply_event, load_state, write_snapshot
from .transaction_log import TransactionLog


class Store:
    def __init__(self, paths: DataPaths, log: TransactionLog | None = None) -> None:
        self.paths = paths
        self.log = log or TransactionLog(paths)
        self.state: State = load_state(paths, self.log)

    @classmethod
    def open(cls, data_dir: str | Path | None = None) -> "Store":
        paths = DataPaths.at(data_dir) if data_dir else DataPaths.default()
        paths.ensure()
        return cls(paths)

    def is_empty(self) -> bool:
        return self.log.is_empty()

    def refresh(self) -> None:
        self.state = load_state(self.paths, self.log)

    def append(
        self,
        event_type: EventType,
        payload: Mapping[str, Any],
        *,
        actor: str = SYSTEM_ACTOR,
        occurred_at: str | None = None,
        notes: str = "",
        snapshot: bool = True,
    ) -> Event:
        event = Event(
            event_id=self.log.next_event_id(occurred_at),
            event_type=event_type,
            occurred_at=occurred_at or now_iso(),
            actor=actor,
            payload=payload,
            notes=notes,
        )
        apply_event(self.state, event)
        try:
            self.log.record(event)
        except Exception:
            self.refresh()
            raise
        if snapshot:
            self.snapshot()
        return event

    def extend(self, events: Iterable[Event], *, snapshot: bool = True) -> None:
        batch = list(events)
        if not batch:
            return
        applied = 0
        try:
            for event in batch:
                apply_event(self.state, event)
                applied += 1
            self.log.record_many(batch)
        except Exception:
            if applied:
                self.refresh()
            raise
        if snapshot:
            self.snapshot()

    def snapshot(self) -> None:
        write_snapshot(self.state, self.paths)
