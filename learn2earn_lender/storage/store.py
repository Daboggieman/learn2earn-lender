"""The single seam between the services and everything on disk.

Services never touch files. They ask a :class:`Store` for the current state
and hand it an event to record; the store owns the ordering that keeps the
log and the projections consistent:

1. apply the event in memory (this is where domain invariants are enforced),
2. append it to the log,
3. refresh the ``current/`` snapshot.

Applying *before* appending means a rejected operation never reaches the log,
so the log can never contain an event that the domain refused.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from ..domain.events import SYSTEM_ACTOR, Event, EventType
from ..validators.dates import now_iso
from .paths import DataPaths
from .projections import State, apply_event, load_state, write_snapshot
from .transaction_log import TransactionLog


class Store:
    """Event log plus the current state projected from it."""

    def __init__(self, paths: DataPaths, log: TransactionLog | None = None) -> None:
        self.paths = paths
        self.log = log or TransactionLog(paths)
        self.state: State = load_state(paths, self.log)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def open(cls, data_dir: str | Path | None = None) -> "Store":
        """Open the data directory, creating it if necessary.

        The returned store has already replayed the log, so ``store.state``
        is the truth as of now.
        """
        paths = DataPaths.at(data_dir) if data_dir else DataPaths.default()
        paths.ensure()
        return cls(paths)

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def is_empty(self) -> bool:
        """True when no events have ever been recorded."""
        return self.log.is_empty()

    def refresh(self) -> None:
        """Discard in-memory state and rebuild it from the log."""
        self.state = load_state(self.paths, self.log)

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

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
        """Record one event and return it."""
        event = Event(
            event_id=self.log.next_event_id(occurred_at),
            event_type=event_type,
            occurred_at=occurred_at or now_iso(),
            actor=actor,
            payload=payload,
            notes=notes,
        )
        self._apply_then_record(event)
        if snapshot:
            self.snapshot()
        return event

    def extend(self, events: Iterable[Event], *, snapshot: bool = True) -> None:
        """Record a batch of already-built events (seeding, import).

        The snapshot is written once at the end rather than per event: seeding
        thousands of records should not rewrite five JSON files thousands of
        times.
        """
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
            # Re-derive from the log rather than trying to invert the events
            # already applied — the log is authoritative by construction.
            if applied:
                self.refresh()
            raise
        if snapshot:
            self.snapshot()

    def snapshot(self) -> None:
        """Write the human-readable ``current/`` projections."""
        write_snapshot(self.state, self.paths)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _apply_then_record(self, event: Event) -> None:
        apply_event(self.state, event)
        try:
            self.log.record(event)
        except Exception:
            # The event is in memory but not on disk; re-derive so the two
            # cannot stay out of step for the rest of the process.
            self.refresh()
            raise
