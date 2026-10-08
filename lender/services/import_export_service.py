from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from ..domain.equipment import (
    UNAVAILABLE_CONDITIONS,
    Condition,
    Resource,
    ResourceStatus,
)
from ..domain.errors import (
    ImportConflict,
    InvariantViolation,
    StorageError,
    ValidationError,
)
from ..domain.events import SYSTEM_ACTOR, Event, EventType, format_event_id
from ..domain.groups import Group
from ..domain.people import Person
from ..domain.taxonomy import TaxonomyNode
from ..domain.transactions import (
    Transaction,
    checkout_payload,
    return_payload,
)
from ..storage import json_repository
from ..storage.projections import rebuild
from ..storage.store import Store
from ..validators.dates import now_iso, parse_datetime, to_iso
from ..validators.ids import validate_id
from ..validators.quantities import require_non_negative, require_positive

EXPORT_FORMAT = "learn2earn-lender/1"

PENDING_PREFIX = "PENDING-"

DATASETS: tuple[str, ...] = ("taxonomy", "groups", "resources", "people", "loans")

CSV_COLUMNS: dict[str, tuple[str, ...]] = {
    "taxonomy": ("id", "name", "type", "parent_id", "status", "created_at"),
    "groups": ("id", "name", "type", "status", "created_at"),
    "resources": (
        "id",
        "name",
        "category_id",
        "subcategory_id",
        "total_quantity",
        "issued_quantity",
        "faulty",
        "damaged",
        "missing",
        "retired",
        "needed_quantity",
        "status",
        "notes",
        "created_at",
    ),
    "people": ("id", "name", "type", "group_id", "status", "notes", "created_at"),
    "loans": (
        "transaction_id",
        "resource_id",
        "borrower_id",
        "quantity",
        "issued_at",
        "due_at",
        "returned_quantity",
        "condition_on_issue",
        "condition_on_return",
        "returned_at",
        "issued_by",
        "returned_by",
        "notes",
    ),
}

OPTIONAL_COLUMNS = frozenset({"created_at"})

IMPORT_MODES: tuple[str, ...] = ("merge", "replace")

FORMATS: tuple[str, ...] = ("json", "csv")

RECORD_FIELDS: dict[EventType, tuple[str, str]] = {
    EventType.TAXONOMY_CREATED: ("node", "taxonomy"),
    EventType.GROUP_CREATED: ("group", "groups"),
    EventType.RESOURCE_CREATED: ("resource", "resources"),
    EventType.PERSON_CREATED: ("person", "people"),
}


def _event_order(event: Event) -> tuple[str, str]:
    return (event.occurred_at, event.event_id)


class ImportExportService:
    def __init__(self, store: Store) -> None:
        self._store = store

    def export_json_document(self) -> dict[str, Any]:
        events = self._store.log.read_all()
        return {
            "format": EXPORT_FORMAT,
            "exported_at": now_iso(),
            "event_count": len(events),
            "events": [event.to_dict() for event in events],
        }

    def export_csv_text(self, dataset: str) -> str:
        name = require_dataset(dataset)
        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer, fieldnames=list(CSV_COLUMNS[name]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(self.rows_for(name))
        return buffer.getvalue()

    def write_export(
        self, path: str | Path, *, fmt: str, dataset: str | None = None
    ) -> dict[str, Any]:
        target = Path(path).expanduser()
        if fmt == "json":
            document = self.export_json_document()
            json_repository.write_json(target, document)
            return {
                "path": str(target),
                "format": "json",
                "events": document["event_count"],
            }
        if fmt == "csv":
            name = require_dataset(dataset)
            rows = self.rows_for(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(self.export_csv_text(name), encoding="utf-8")
            return {
                "path": str(target),
                "format": "csv",
                "dataset": name,
                "rows": len(rows),
            }
        raise ValidationError(
            f"unknown export format {fmt!r}: expected one of {', '.join(FORMATS)}"
        )

    def import_file(
        self,
        path: str | Path,
        *,
        fmt: str,
        dataset: str | None = None,
        mode: str = "merge",
    ) -> dict[str, Any]:
        source = Path(path).expanduser()
        if not source.is_file():
            raise StorageError(f"no import file at {source}")
        clean_mode = require_mode(mode)

        if fmt == "json":
            return self.import_json_document(
                json_repository.read_json(source), mode=clean_mode
            )
        if fmt == "csv":
            name = require_dataset(dataset)
            text = source.read_text(encoding="utf-8")
            return self.import_csv_text(text, name, mode=clean_mode)
        raise ValidationError(
            f"unknown import format {fmt!r}: expected one of {', '.join(FORMATS)}"
        )

    def import_json_document(
        self, document: Any, *, mode: str = "merge"
    ) -> dict[str, Any]:
        clean_mode = require_mode(mode)
        if not isinstance(document, dict):
            raise ValidationError("import file must contain a JSON object")
        if document.get("format") != EXPORT_FORMAT:
            raise ValidationError(
                f"unrecognised export format {document.get('format')!r}; "
                f"expected {EXPORT_FORMAT!r}"
            )
        raw_events = document.get("events")
        if not isinstance(raw_events, list):
            raise ValidationError("import document is missing an 'events' array")

        incoming = [Event.from_dict(entry) for entry in raw_events]
        return self._apply_events(incoming, clean_mode, "json")

    def import_csv_text(
        self, text: str, dataset: str, *, mode: str = "merge"
    ) -> dict[str, Any]:
        name = require_dataset(dataset)
        clean_mode = require_mode(mode)
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        require_columns(name, reader.fieldnames)
        incoming = self._events_from_rows(name, rows)
        if clean_mode == "merge":
            self._reject_existing_records(incoming)
        return self._apply_events(incoming, clean_mode, f"csv:{name}")

    def _reject_existing_records(self, incoming: Sequence[Event]) -> None:
        state = self._store.state
        for event in incoming:
            key = self._record_key(event, state)
            if key is None:
                continue
            collection = getattr(state, key[0])
            if key[1] in collection:
                raise ImportConflict(
                    f"{event.event_type.value}: {key[1]!r} already exists in this "
                    f"store; re-run with --mode replace to overwrite it, or edit "
                    f"the file to use a different id"
                )

    @staticmethod
    def _record_key(event: Event, state) -> tuple[str, str] | None:
        fields = RECORD_FIELDS.get(event.event_type)
        if fields is not None:
            record = event.payload.get(fields[0]) or {}
            return (fields[1], str(record.get("id", "")))
        if event.event_type is EventType.LOAN_CHECKED_OUT:
            return ("loans", str(event.payload.get("transaction_id", "")))
        return None

    def rows_for(self, dataset: str) -> list[dict[str, Any]]:
        name = require_dataset(dataset)
        state = self._store.state
        if name == "resources":
            return [
                resource_row(resource)
                for resource in sorted(state.resources.values(), key=lambda r: r.id)
            ]
        if name == "people":
            return [
                {
                    "id": person.id,
                    "name": person.name,
                    "type": person.type.value,
                    "group_id": person.group_id,
                    "status": person.status.value,
                    "notes": person.notes,
                    "created_at": person.created_at,
                }
                for person in sorted(state.people.values(), key=lambda p: p.id)
            ]
        if name == "groups":
            return [
                {
                    "id": group.id,
                    "name": group.name,
                    "type": group.type.value,
                    "status": group.status.value,
                    "created_at": group.created_at,
                }
                for group in sorted(state.groups.values(), key=lambda g: g.id)
            ]
        if name == "taxonomy":
            return [
                {
                    "id": node.id,
                    "name": node.name,
                    "type": node.type.value,
                    "parent_id": node.parent_id or "",
                    "status": node.status.value,
                    "created_at": node.created_at,
                }
                for node in sorted(state.taxonomy.values(), key=lambda n: n.id)
            ]
        return [
            loan_row(loan)
            for loan in sorted(
                state.loans.values(), key=lambda loan: loan.transaction_id
            )
        ]

    def _apply_events(
        self, incoming: list[Event], mode: str, source: str
    ) -> dict[str, Any]:
        if mode == "replace":
            ordered = sorted(incoming, key=_event_order)
            skipped = 0
            tail = ordered
        else:
            existing = self._store.log.read_all()
            ordered, _, skipped = self._merge(existing, incoming)
            tail = ordered[len(existing) :]

        self._validate(ordered, source)

        if mode == "replace":
            self._wipe()

        framed = [
            self._assign_id(event)
            for event in tail
        ]
        self._store.extend(framed)

        return {
            "source": source,
            "mode": mode,
            "imported": len(framed),
            "skipped": skipped,
            "total_events": len(self._store.log.read_all()),
        }

    def _assign_id(self, event: Event) -> Event:
        if not event.event_id.startswith(PENDING_PREFIX):
            return event
        return replace(
            event, event_id=self._store.log.next_event_id(event.occurred_at)
        )

    def _merge(
        self, existing: list[Event], incoming: list[Event]
    ) -> tuple[list[Event], int, int]:
        known = {event.event_id: event for event in existing}
        taken = set(known)
        merged = list(existing)
        added = 0
        skipped = 0

        for event in sorted(incoming, key=_event_order):
            current = known.get(event.event_id)
            if current is not None:
                if current.to_dict() == event.to_dict():
                    skipped += 1
                    continue
                event = self._reassign(event, taken)
            merged.append(event)
            taken.add(event.event_id)
            added += 1

        return merged, added, skipped

    @staticmethod
    def _reassign(event: Event, taken: set[str]) -> Event:
        sequence = 1
        while format_event_id(event.date_key, sequence) in taken:
            sequence += 1
        return replace(event, event_id=format_event_id(event.date_key, sequence))

    def _validate(self, events: Sequence[Event], source: str) -> None:
        try:
            rebuild(events)
        except (ValidationError, InvariantViolation) as exc:
            raise ValidationError(
                f"{source}: import rejected, the data is not valid — {exc}"
            ) from exc
        except StorageError as exc:
            raise ImportConflict(
                f"{source}: import rejected, the data refers to records that "
                f"are missing — {exc}"
            ) from exc

    def _wipe(self) -> None:
        for directory in (
            self._store.paths.transactions_dir,
            self._store.paths.current_dir,
        ):
            for path in json_repository.list_json_files(directory):
                json_repository.delete_file(path)
        self._store.refresh()

    def _events_from_rows(
        self, dataset: str, rows: list[dict[str, Any]]
    ) -> list[Event]:
        builders: dict[str, Callable[[dict[str, Any], str], list[Event]]] = {
            "taxonomy": self._taxonomy_events,
            "groups": self._group_events,
            "resources": self._resource_events,
            "people": self._people_events,
            "loans": self._loans_events,
        }
        builder = builders[require_dataset(dataset)]
        events: list[Event] = []
        for index, row in enumerate(rows, start=2):
            pending = f"{PENDING_PREFIX}{index:05d}"
            try:
                events.extend(builder(row, pending))
            except ValidationError as exc:
                raise ValidationError(f"{dataset} row {index}: {exc}") from exc
        return events

    def _taxonomy_events(self, row: dict[str, Any], pending: str) -> list[Event]:
        moment = self._moment(row)
        node = TaxonomyNode.from_dict(
            {
                "id": cell(row, "id"),
                "name": cell(row, "name"),
                "type": cell(row, "type"),
                "parent_id": cell(row, "parent_id") or None,
                "status": cell(row, "status") or "active",
                "created_at": moment,
            }
        )
        return [
            self._event(
                EventType.TAXONOMY_CREATED,
                {"node": node.to_dict()},
                pending,
                occurred_at=moment,
            )
        ]

    def _group_events(self, row: dict[str, Any], pending: str) -> list[Event]:
        moment = self._moment(row)
        group = Group.from_dict(
            {
                "id": cell(row, "id"),
                "name": cell(row, "name"),
                "type": cell(row, "type"),
                "status": cell(row, "status") or "active",
                "created_at": moment,
            }
        )
        return [
            self._event(
                EventType.GROUP_CREATED,
                {"group": group.to_dict()},
                pending,
                occurred_at=moment,
            )
        ]

    def _resource_events(self, row: dict[str, Any], pending: str) -> list[Event]:
        moment = self._moment(row)
        total = require_non_negative(cell(row, "total_quantity"), "total_quantity")
        counts = {
            condition.value: require_non_negative(
                cell(row, condition.value) or 0, condition.value
            )
            for condition in UNAVAILABLE_CONDITIONS
        }
        unavailable = sum(counts.values())
        if unavailable > total:
            raise ValidationError(
                f"{unavailable} unavailable unit(s) exceed the total of {total}"
            )
        resource = Resource.from_dict(
            {
                "id": cell(row, "id"),
                "name": cell(row, "name"),
                "category_id": cell(row, "category_id"),
                "subcategory_id": cell(row, "subcategory_id"),
                "total_quantity": total,
                "available_quantity": total - unavailable,
                "issued_quantity": 0,
                "condition_counts": {},
                "needed_quantity": require_non_negative(
                    cell(row, "needed_quantity") or 0, "needed_quantity"
                ),
                "status": cell(row, "status") or ResourceStatus.ACTIVE.value,
                "notes": cell(row, "notes"),
                "created_at": moment,
            }
        )
        events = [
            self._event(
                EventType.RESOURCE_CREATED,
                {"resource": resource.to_dict()},
                pending,
                occurred_at=moment,
            )
        ]
        for condition, quantity in counts.items():
            if not quantity:
                continue
            events.append(
                self._event(
                    EventType.RESOURCE_CONDITION_CHANGED,
                    {
                        "resource_id": resource.id,
                        "from": Condition.GOOD.value,
                        "to": condition,
                        "quantity": quantity,
                    },
                    f"{pending}-{condition}",
                    occurred_at=moment,
                )
            )
        return events

    def _people_events(self, row: dict[str, Any], pending: str) -> list[Event]:
        moment = self._moment(row)
        person = Person.from_dict(
            {
                "id": cell(row, "id"),
                "name": cell(row, "name"),
                "type": cell(row, "type"),
                "group_id": cell(row, "group_id"),
                "status": cell(row, "status") or "active",
                "notes": cell(row, "notes"),
                "created_at": moment,
            }
        )
        return [
            self._event(
                EventType.PERSON_CREATED,
                {"person": person.to_dict()},
                pending,
                occurred_at=moment,
            )
        ]

    def _loans_events(self, row: dict[str, Any], pending: str) -> list[Event]:
        transaction_id = validate_id(cell(row, "transaction_id"), "transaction_id")
        resource_id = cell(row, "resource_id")
        borrower_id = cell(row, "borrower_id")
        quantity = require_positive(cell(row, "quantity"), "quantity")
        issued_at = to_iso(parse_datetime(cell(row, "issued_at"), "issued_at"))
        due_at = to_iso(parse_datetime(cell(row, "due_at"), "due_at"))

        events = [
            self._event(
                EventType.LOAN_CHECKED_OUT,
                checkout_payload(
                    transaction_id=transaction_id,
                    resource_id=resource_id,
                    borrower_id=borrower_id,
                    quantity=quantity,
                    due_at=due_at,
                    condition_on_issue=_condition(row, "condition_on_issue"),
                    issued_by=cell(row, "issued_by") or SYSTEM_ACTOR,
                    notes=cell(row, "notes"),
                ),
                pending,
                occurred_at=issued_at,
            )
        ]

        returned = require_non_negative(
            cell(row, "returned_quantity") or 0, "returned_quantity"
        )
        if returned > quantity:
            raise ValidationError(
                f"returned_quantity {returned} exceeds quantity {quantity}"
            )
        if returned:
            events.append(
                self._event(
                    EventType.LOAN_RETURNED,
                    return_payload(
                        transaction_id=f"{transaction_id}-R",
                        checkout_transaction_id=transaction_id,
                        resource_id=resource_id,
                        borrower_id=borrower_id,
                        quantity=returned,
                        condition_on_return=_condition(row, "condition_on_return"),
                        returned_by=cell(row, "returned_by") or SYSTEM_ACTOR,
                        notes=cell(row, "notes"),
                    ),
                    f"{pending}-R",
                    occurred_at=to_iso(
                        parse_datetime(
                            cell(row, "returned_at") or issued_at, "returned_at"
                        )
                    ),
                )
            )
        return events

    def _event(
        self,
        event_type: EventType,
        payload: dict[str, Any],
        pending: str,
        *,
        occurred_at: str | None = None,
    ) -> Event:
        return Event(
            event_id=pending,
            event_type=event_type,
            occurred_at=occurred_at or now_iso(),
            actor=SYSTEM_ACTOR,
            payload=payload,
        )

    @staticmethod
    def _moment(row: dict[str, Any]) -> str:
        stamp = cell(row, "created_at")
        if not stamp:
            return now_iso()
        return to_iso(parse_datetime(stamp, "created_at"))


def resource_row(resource: Resource) -> dict[str, Any]:
    counts = resource.condition_counts
    return {
        "id": resource.id,
        "name": resource.name,
        "category_id": resource.category_id,
        "subcategory_id": resource.subcategory_id,
        "total_quantity": resource.total_quantity,
        "issued_quantity": resource.issued_quantity,
        "faulty": counts.get("faulty", 0),
        "damaged": counts.get("damaged", 0),
        "missing": counts.get("missing", 0),
        "retired": counts.get("retired", 0),
        "needed_quantity": resource.needed_quantity,
        "status": resource.status.value,
        "notes": resource.notes,
        "created_at": resource.created_at,
    }


def loan_row(loan: Transaction) -> dict[str, Any]:
    return {
        "transaction_id": loan.transaction_id,
        "resource_id": loan.resource_id,
        "borrower_id": loan.borrower_id,
        "quantity": loan.quantity,
        "issued_at": loan.issued_at,
        "due_at": loan.due_at,
        "returned_quantity": loan.returned_quantity,
        "condition_on_issue": loan.condition_on_issue.value,
        "condition_on_return": (
            loan.condition_on_return.value if loan.condition_on_return else ""
        ),
        "returned_at": loan.returned_at or "",
        "issued_by": loan.issued_by,
        "returned_by": loan.returned_by or "",
        "notes": loan.notes,
    }


def cell(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    return "" if value is None else str(value).strip()


def _condition(row: dict[str, Any], key: str) -> Condition:
    return Condition.parse(cell(row, key) or Condition.GOOD.value)


def require_dataset(dataset: str | None) -> str:
    if dataset is None:
        raise ValidationError(
            f"a dataset is required for CSV; choose one of {', '.join(DATASETS)}"
        )
    if dataset not in DATASETS:
        raise ValidationError(
            f"unknown dataset {dataset!r}; choose one of {', '.join(DATASETS)}"
        )
    return dataset


def require_mode(mode: str) -> str:
    text = str(mode).strip().lower()
    if text not in IMPORT_MODES:
        raise ValidationError(
            f"unknown import mode {mode!r}; choose one of {', '.join(IMPORT_MODES)}"
        )
    return text


def require_columns(dataset: str, fieldnames: Iterable[str] | None) -> None:
    if not fieldnames:
        raise ValidationError(f"{dataset} CSV is empty and has no header row")
    missing = set(CSV_COLUMNS[dataset]) - OPTIONAL_COLUMNS - set(fieldnames)
    if missing:
        raise ValidationError(
            f"{dataset} CSV is missing column(s): {', '.join(sorted(missing))}"
        )
