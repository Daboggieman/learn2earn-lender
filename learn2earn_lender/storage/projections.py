from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping

from ..domain import groups as group_models
from ..domain import people as people_models
from ..domain import taxonomy as taxonomy_models
from ..domain.equipment import Condition, Resource, ResourceStatus
from ..domain.errors import StorageError
from ..domain.events import Event, EventType
from ..domain.transactions import Transaction
from ..validators.quantities import require_non_negative, require_positive
from . import json_repository
from .paths import DataPaths
from .transaction_log import TransactionLog

RESOURCE_UPDATE_FIELDS = frozenset(
    {"name", "category_id", "subcategory_id", "needed_quantity", "notes", "total_quantity"}
)
TAXONOMY_UPDATE_FIELDS = frozenset({"name"})
GROUP_UPDATE_FIELDS = frozenset({"name", "status"})
PERSON_UPDATE_FIELDS = frozenset({"name", "group_id", "type", "status", "notes"})


@dataclass
class State:
    resources: dict[str, Resource] = field(default_factory=dict)
    taxonomy: dict[str, taxonomy_models.TaxonomyNode] = field(default_factory=dict)
    groups: dict[str, group_models.Group] = field(default_factory=dict)
    people: dict[str, people_models.Person] = field(default_factory=dict)
    loans: dict[str, Transaction] = field(default_factory=dict)
    events_applied: int = 0
    last_event_at: str | None = None

    def active_resources(self) -> list[Resource]:
        return sorted(
            (r for r in self.resources.values() if r.is_active), key=lambda r: r.id
        )

    def resources_in_category(self, category_id: str) -> list[Resource]:
        return sorted(
            (r for r in self.resources.values() if r.category_id == category_id),
            key=lambda r: r.id,
        )

    def resources_in_subcategory(self, subcategory_id: str) -> list[Resource]:
        return sorted(
            (r for r in self.resources.values() if r.subcategory_id == subcategory_id),
            key=lambda r: r.id,
        )

    def categories(self) -> list[taxonomy_models.TaxonomyNode]:
        return sorted(
            (node for node in self.taxonomy.values() if node.is_category),
            key=lambda node: node.name.lower(),
        )

    def subcategories(
        self, category_id: str | None = None
    ) -> list[taxonomy_models.TaxonomyNode]:
        nodes = [
            node
            for node in self.taxonomy.values()
            if node.is_subcategory
            and (category_id is None or node.parent_id == category_id)
        ]
        return sorted(nodes, key=lambda node: node.name.lower())

    def people_in_group(self, group_id: str) -> list[people_models.Person]:
        return sorted(
            (p for p in self.people.values() if p.group_id == group_id),
            key=lambda p: p.name.lower(),
        )

    def loans_for_borrower(self, borrower_id: str) -> list[Transaction]:
        return sorted(
            (loan for loan in self.loans.values() if loan.borrower_id == borrower_id),
            key=lambda loan: (loan.issued_at, loan.transaction_id),
        )

    def loans_for_resource(self, resource_id: str) -> list[Transaction]:
        return sorted(
            (loan for loan in self.loans.values() if loan.resource_id == resource_id),
            key=lambda loan: (loan.issued_at, loan.transaction_id),
        )

    def open_loans(self, at: datetime | None = None) -> list[Transaction]:
        return sorted(
            (loan for loan in self.loans.values() if not loan.is_returned),
            key=lambda loan: (loan.due_at, loan.transaction_id),
        )

    def overdue_loans(self, at: datetime | None = None) -> list[Transaction]:
        return [loan for loan in self.open_loans(at) if loan.is_overdue(at)]

    def resource_or_raise(self, resource_id: str) -> Resource:
        try:
            return self.resources[resource_id]
        except KeyError as exc:
            raise StorageError(
                f"event log references unknown resource {resource_id!r}"
            ) from exc

    def taxonomy_or_raise(self, node_id: str) -> taxonomy_models.TaxonomyNode:
        try:
            return self.taxonomy[node_id]
        except KeyError as exc:
            raise StorageError(
                f"event log references unknown taxonomy node {node_id!r}"
            ) from exc

    def group_or_raise(self, group_id: str) -> group_models.Group:
        try:
            return self.groups[group_id]
        except KeyError as exc:
            raise StorageError(f"event log references unknown group {group_id!r}") from exc

    def person_or_raise(self, person_id: str) -> people_models.Person:
        try:
            return self.people[person_id]
        except KeyError as exc:
            raise StorageError(f"event log references unknown person {person_id!r}") from exc


def rebuild(events: Iterable[Event]) -> State:
    state = State()
    for event in events:
        apply_event(state, event)
    return state


def apply_event(state: State, event: Event) -> None:
    handler = _HANDLERS.get(event.event_type)
    if handler is None:
        raise StorageError(
            f"cannot replay unsupported event type {event.event_type.value!r}"
        )
    handler(state, event)
    state.events_applied += 1
    state.last_event_at = event.occurred_at


def _require(payload: Mapping[str, Any], key: str, event: Event) -> Any:
    if key not in payload:
        raise StorageError(
            f"{event.event_type.value} event {event.event_id} is missing {key!r}"
        )
    return payload[key]


def _apply_resource_created(state: State, event: Event) -> None:
    raw = _require(event.payload, "resource", event)
    resource = Resource.from_dict(raw)
    state.resources[resource.id] = resource


def _apply_resource_updated(state: State, event: Event) -> None:
    resource = state.resource_or_raise(str(_require(event.payload, "resource_id", event)))
    changes = dict(_require(event.payload, "changes", event))

    unknown = set(changes) - RESOURCE_UPDATE_FIELDS
    if unknown:
        raise StorageError(
            f"{event.event_id}: resource.updated cannot change {', '.join(sorted(unknown))}"
        )

    if "total_quantity" in changes:
        resource.set_total_quantity(
            require_non_negative(changes.pop("total_quantity"), "total_quantity")
        )

    for key, value in changes.items():
        if key == "needed_quantity":
            value = require_non_negative(value, "needed_quantity")
        setattr(resource, key, value)

    resource.check_invariant()
    resource.updated_at = event.occurred_at


def _apply_resource_removed(state: State, event: Event) -> None:
    resource = state.resource_or_raise(str(_require(event.payload, "resource_id", event)))
    if resource.issued_quantity:
        raise StorageError(
            f"{event.event_id}: cannot remove resource {resource.id}; "
            f"{resource.issued_quantity} unit(s) are still on loan"
        )
    resource.status = ResourceStatus.REMOVED
    resource.updated_at = event.occurred_at


def _apply_condition_changed(state: State, event: Event) -> None:
    resource = state.resource_or_raise(str(_require(event.payload, "resource_id", event)))
    source = Condition.parse(_require(event.payload, "from", event))
    destination = Condition.parse(_require(event.payload, "to", event))
    quantity = require_positive(_require(event.payload, "quantity", event), "quantity")
    resource.transfer_condition(source, destination, quantity)
    resource.updated_at = event.occurred_at


def _apply_taxonomy_created(state: State, event: Event) -> None:
    node = taxonomy_models.TaxonomyNode.from_dict(_require(event.payload, "node", event))
    state.taxonomy[node.id] = node


def _apply_taxonomy_updated(state: State, event: Event) -> None:
    node = state.taxonomy_or_raise(str(_require(event.payload, "node_id", event)))
    changes = dict(_require(event.payload, "changes", event))
    unknown = set(changes) - TAXONOMY_UPDATE_FIELDS
    if unknown:
        raise StorageError(
            f"{event.event_id}: taxonomy.updated cannot change {', '.join(sorted(unknown))}"
        )
    for key, value in changes.items():
        setattr(node, key, value)
    node.updated_at = event.occurred_at


def _apply_taxonomy_removed(state: State, event: Event) -> None:
    node = state.taxonomy_or_raise(str(_require(event.payload, "node_id", event)))
    node.status = taxonomy_models.TaxonomyStatus.REMOVED
    node.updated_at = event.occurred_at


def _apply_group_created(state: State, event: Event) -> None:
    group = group_models.Group.from_dict(_require(event.payload, "group", event))
    state.groups[group.id] = group


def _apply_group_updated(state: State, event: Event) -> None:
    group = state.group_or_raise(str(_require(event.payload, "group_id", event)))
    changes = dict(_require(event.payload, "changes", event))
    unknown = set(changes) - GROUP_UPDATE_FIELDS
    if unknown:
        raise StorageError(
            f"{event.event_id}: group.updated cannot change {', '.join(sorted(unknown))}"
        )
    if "status" in changes:
        changes["status"] = group_models.GroupStatus.parse(changes["status"])
    for key, value in changes.items():
        setattr(group, key, value)
    group.updated_at = event.occurred_at


def _apply_person_created(state: State, event: Event) -> None:
    person = people_models.Person.from_dict(_require(event.payload, "person", event))
    state.people[person.id] = person


def _apply_person_updated(state: State, event: Event) -> None:
    person = state.person_or_raise(str(_require(event.payload, "person_id", event)))
    changes = dict(_require(event.payload, "changes", event))
    unknown = set(changes) - PERSON_UPDATE_FIELDS
    if unknown:
        raise StorageError(
            f"{event.event_id}: person.updated cannot change {', '.join(sorted(unknown))}"
        )
    if "type" in changes:
        changes["type"] = people_models.PersonType.parse(changes["type"])
    if "status" in changes:
        changes["status"] = people_models.PersonStatus.parse(changes["status"])
    for key, value in changes.items():
        setattr(person, key, value)
    person.updated_at = event.occurred_at


def _apply_loan_checked_out(state: State, event: Event) -> None:
    loan = Transaction.from_checkout_event(event.payload, event.occurred_at)
    resource = state.resource_or_raise(loan.resource_id)
    resource.require_active("lend")
    resource.issue_units(loan.quantity)
    resource.updated_at = event.occurred_at
    state.loans[loan.transaction_id] = loan


def _apply_loan_returned(state: State, event: Event) -> None:
    checkout_id = str(_require(event.payload, "checkout_transaction_id", event))
    try:
        loan = state.loans[checkout_id]
    except KeyError as exc:
        raise StorageError(
            f"{event.event_id}: return references unknown checkout {checkout_id!r}"
        ) from exc

    quantity = require_positive(_require(event.payload, "quantity", event), "quantity")
    condition = Condition.parse(
        event.payload.get("condition_on_return", Condition.GOOD.value)
    )
    resource = state.resource_or_raise(loan.resource_id)
    resource.release_units(quantity, condition)
    resource.updated_at = event.occurred_at
    loan.apply_return(event.payload, event.occurred_at)


_HANDLERS = {
    EventType.RESOURCE_CREATED: _apply_resource_created,
    EventType.RESOURCE_UPDATED: _apply_resource_updated,
    EventType.RESOURCE_REMOVED: _apply_resource_removed,
    EventType.RESOURCE_CONDITION_CHANGED: _apply_condition_changed,
    EventType.TAXONOMY_CREATED: _apply_taxonomy_created,
    EventType.TAXONOMY_UPDATED: _apply_taxonomy_updated,
    EventType.TAXONOMY_REMOVED: _apply_taxonomy_removed,
    EventType.GROUP_CREATED: _apply_group_created,
    EventType.GROUP_UPDATED: _apply_group_updated,
    EventType.PERSON_CREATED: _apply_person_created,
    EventType.PERSON_UPDATED: _apply_person_updated,
    EventType.LOAN_CHECKED_OUT: _apply_loan_checked_out,
    EventType.LOAN_RETURNED: _apply_loan_returned,
}


def load_state(paths: DataPaths, log: TransactionLog) -> State:
    return rebuild(log.read_all())


def write_snapshot(state: State, paths: DataPaths) -> None:
    json_repository.write_json(
        paths.inventory_file,
        {
            "resources": [
                resource.to_dict()
                for resource in sorted(state.resources.values(), key=lambda r: r.id)
            ]
        },
    )
    json_repository.write_json(
        paths.taxonomy_file,
        {
            "nodes": [
                node.to_dict()
                for node in sorted(state.taxonomy.values(), key=lambda n: n.id)
            ]
        },
    )
    json_repository.write_json(
        paths.groups_file,
        {
            "groups": [
                group.to_dict()
                for group in sorted(state.groups.values(), key=lambda g: g.id)
            ]
        },
    )
    json_repository.write_json(
        paths.people_file,
        {
            "people": [
                person.to_dict()
                for person in sorted(state.people.values(), key=lambda p: p.id)
            ]
        },
    )
    json_repository.write_json(
        paths.loans_file,
        {
            "loans": [
                loan.to_dict()
                for loan in sorted(state.loans.values(), key=lambda l: l.transaction_id)
            ]
        },
    )
