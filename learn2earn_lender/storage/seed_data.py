from __future__ import annotations

import random
from dataclasses import replace
from datetime import datetime, timedelta

from ..domain.equipment import Condition, ResourceStatus, empty_condition_counts
from ..domain.events import SYSTEM_ACTOR, Event, EventType, format_event_id
from ..domain.groups import GroupStatus, GroupType
from ..domain.people import PersonStatus, PersonType
from ..domain.taxonomy import TaxonomyStatus, TaxonomyType
from ..domain.transactions import checkout_payload, return_payload
from ..validators.dates import to_iso
from ..validators.ids import next_sequential_id
from ..validators.strings import slugify

SEED_START = datetime(2026, 1, 1, 8, 0, 0)

SEED_TAXONOMY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Electronics", ("desktop-computer", "laptop")),
    ("Accessories", ("keyboard", "mouse", "mouse-pad", "others")),
    ("Utilities", ("chairs", "internet-access", "facility-access")),
)

SEED_COHORTS: tuple[str, ...] = (
    "cluster-1-feb",
    "cluster-2-feb",
    "cluster-3-feb",
    "cluster-4-feb",
    "july-cohort",
)

SEED_TRIALS: tuple[str, ...] = tuple(f"trial-period-{index}" for index in range(1, 7))

SEED_RESOURCES: tuple[dict[str, object], ...] = (
    {
        "id": "R001",
        "name": "Laptop",
        "category": "Electronics",
        "subcategory": "laptop",
        "total": 10,
    },
    {
        "id": "R002",
        "name": "Keyboard",
        "category": "Accessories",
        "subcategory": "keyboard",
        "total": 5,
    },
    {
        "id": "R003",
        "name": "Headset",
        "category": "Accessories",
        "subcategory": "others",
        "total": 3,
    },
)

SEED_PEOPLE: tuple[tuple[str, str, str], ...] = (
    ("F001", "Ada", "cluster-1-feb"),
    ("F002", "John", "cluster-2-feb"),
    ("F003", "Grace", "cluster-3-feb"),
)


def category_id(name: str) -> str:
    return slugify(name, "category name")


def subcategory_id(category_name: str, subcategory_name: str) -> str:
    return (
        f"{slugify(category_name, 'category name')}"
        f"-{slugify(subcategory_name, 'subcategory name')}"
    )


class _EventBuilder:
    def __init__(self, start: datetime) -> None:
        self._clock = start
        self._counters: dict[str, int] = {}
        self.events: list[Event] = []

    def tick(self, seconds: int = 1) -> str:
        self._clock += timedelta(seconds=seconds)
        return to_iso(self._clock)

    def now(self) -> str:
        return to_iso(self._clock)

    def add(
        self,
        event_type: EventType,
        payload: dict[str, object],
        *,
        occurred_at: str | None = None,
        notes: str = "",
    ) -> Event:
        moment = occurred_at or self.tick()
        date_key = moment[:10]
        sequence = self._counters.get(date_key, 0) + 1
        self._counters[date_key] = sequence
        event = Event(
            event_id=format_event_id(date_key, sequence),
            event_type=event_type,
            occurred_at=moment,
            actor=SYSTEM_ACTOR,
            payload=payload,
            notes=notes,
        )
        self.events.append(event)
        return event


def renumber_events(events: list[Event]) -> list[Event]:
    ordered = sorted(events, key=lambda event: (event.occurred_at, event.event_id))
    counters: dict[str, int] = {}
    result: list[Event] = []
    for event in ordered:
        key = event.date_key
        counters[key] = counters.get(key, 0) + 1
        result.append(replace(event, event_id=format_event_id(key, counters[key])))
    return result


def baseline_events(start: datetime | None = None) -> list[Event]:
    builder = _EventBuilder(start or SEED_START)
    _emit_taxonomy(builder)
    _emit_groups(builder, list(SEED_COHORTS), list(SEED_TRIALS))
    _emit_resources(builder, SEED_RESOURCES)
    _emit_people(
        builder,
        [(pid, name, "fellow", cohort) for pid, name, cohort in SEED_PEOPLE],
    )
    return builder.events


def _emit_taxonomy(builder: _EventBuilder) -> None:
    for category_name, subcategory_names in SEED_TAXONOMY:
        cat_id = category_id(category_name)
        moment = builder.tick()
        builder.add(
            EventType.TAXONOMY_CREATED,
            {
                "node": {
                    "id": cat_id,
                    "name": category_name,
                    "type": TaxonomyType.CATEGORY.value,
                    "parent_id": None,
                    "status": TaxonomyStatus.ACTIVE.value,
                    "created_at": moment,
                    "updated_at": moment,
                }
            },
            occurred_at=moment,
        )
        for subcategory_name in subcategory_names:
            sub_moment = builder.tick()
            builder.add(
                EventType.TAXONOMY_CREATED,
                {
                    "node": {
                        "id": subcategory_id(category_name, subcategory_name),
                        "name": subcategory_name,
                        "type": TaxonomyType.SUBCATEGORY.value,
                        "parent_id": cat_id,
                        "status": TaxonomyStatus.ACTIVE.value,
                        "created_at": sub_moment,
                        "updated_at": sub_moment,
                    }
                },
                occurred_at=sub_moment,
            )


def _emit_groups(builder: _EventBuilder, cohorts: list[str], trials: list[str]) -> None:
    existing: list[str] = []
    for name, group_type in [
        *((cohort, GroupType.COHORT) for cohort in cohorts),
        *((trial, GroupType.TRIAL) for trial in trials),
    ]:
        group_id = next_sequential_id("G", existing, width=3)
        existing.append(group_id)
        moment = builder.tick()
        builder.add(
            EventType.GROUP_CREATED,
            {
                "group": {
                    "id": group_id,
                    "name": name,
                    "type": group_type.value,
                    "status": GroupStatus.ACTIVE.value,
                    "created_at": moment,
                    "updated_at": moment,
                }
            },
            occurred_at=moment,
        )


def _emit_resources(
    builder: _EventBuilder,
    resources: tuple[dict[str, object], ...] | list[dict[str, object]],
) -> None:
    for entry in resources:
        cat_id = category_id(str(entry["category"]))
        sub_id = subcategory_id(str(entry["category"]), str(entry["subcategory"]))
        total = int(entry["total"])
        moment = builder.tick()
        builder.add(
            EventType.RESOURCE_CREATED,
            {
                "resource": {
                    "id": entry["id"],
                    "name": entry["name"],
                    "category_id": cat_id,
                    "subcategory_id": sub_id,
                    "total_quantity": total,
                    "available_quantity": total,
                    "issued_quantity": 0,
                    "condition_counts": empty_condition_counts(),
                    "needed_quantity": int(entry.get("needed", 0)),
                    "status": ResourceStatus.ACTIVE.value,
                    "created_at": moment,
                    "updated_at": moment,
                    "notes": str(entry.get("notes", "")),
                }
            },
            occurred_at=moment,
        )


def _emit_people(builder: _EventBuilder, people: list[tuple[str, str, str, str]]) -> None:
    group_ids_by_name = {
        str(event.payload["group"]["name"]): str(event.payload["group"]["id"])
        for event in builder.events
        if event.event_type is EventType.GROUP_CREATED
    }
    for person_id, name, person_type, group_name in people:
        moment = builder.tick()
        builder.add(
            EventType.PERSON_CREATED,
            {
                "person": {
                    "id": person_id,
                    "name": name,
                    "type": person_type,
                    "group_id": group_ids_by_name[group_name],
                    "status": PersonStatus.ACTIVE.value,
                    "created_at": moment,
                    "updated_at": moment,
                    "notes": "",
                }
            },
            occurred_at=moment,
        )


FIRST_NAMES: tuple[str, ...] = (
    "Ada", "John", "Grace", "Amara", "Chidi", "Ngozi", "Tunde", "Fatima", "Emeka", "Zainab",
    "Kwame", "Aisha", "Sekou", "Yemi", "Nadia", "Obi", "Lerato", "Hassan", "Ifeoma", "Musa",
    "Thandi", "Kofi", "Rania", "Bola", "Sipho", "Amina", "Femi", "Nkechi", "Ibrahim", "Chiamaka",
    "Dayo", "Halima", "Uche", "Salma", "Bashir", "Adaeze", "Yusuf", "Temi", "Nuru", "Obinna",
)

LAST_NAMES: tuple[str, ...] = (
    "Okafor", "Mensah", "Adeyemi", "Bello", "Nwosu", "Kamau", "Diallo", "Abubakar", "Mwangi", "Eze",
    "Owusu", "Traore", "Balogun", "Chikwe", "Sesay", "Achebe", "Dlamini", "Farouk", "Ige", "Jalloh",
    "Kone", "Lawal", "Mbeki", "Ndiaye", "Ogundipe", "Peters", "Quaye", "Rashid", "Sow", "Toure",
    "Umeh", "Vandi", "Wanjiru", "Yakubu", "Zulu", "Anyanwu", "Boateng", "Coker", "Danso", "Eshiet",
)

MOCK_STOCK: dict[tuple[str, str], tuple[int, int]] = {
    ("Electronics", "desktop-computer"): (12, 4),
    ("Electronics", "laptop"): (25, 6),
    ("Accessories", "keyboard"): (30, 8),
    ("Accessories", "mouse"): (30, 8),
    ("Accessories", "mouse-pad"): (20, 10),
    ("Accessories", "others"): (15, 5),
    ("Utilities", "chairs"): (40, 12),
    ("Utilities", "internet-access"): (10, 2),
    ("Utilities", "facility-access"): (8, 2),
}

MOCK_SLOTS: tuple[tuple[str, str, int, int], ...] = tuple(
    (category_name, subcategory_name, *MOCK_STOCK[(category_name, subcategory_name)])
    for category_name, subcategory_names in SEED_TAXONOMY
    for subcategory_name in subcategory_names
)


def mock_events(
    *,
    fellows: int = 0,
    piscine: int = 0,
    equipment: int = 0,
    cohorts: int = 4,
    trials: int = 6,
    loans: int = 0,
    seed: int = 20260101,
    start: datetime | None = None,
) -> list[Event]:
    if min(fellows, piscine, equipment, cohorts, trials, loans) < 0:
        raise ValueError("mock counts must not be negative")

    rng = random.Random(seed)
    builder = _EventBuilder(start or SEED_START)

    cohort_names = [f"cluster-{index + 1}-mock" for index in range(cohorts)]
    trial_names = [f"mock-trial-{index + 1}" for index in range(trials)]

    _emit_taxonomy(builder)
    _emit_groups(builder, cohort_names, trial_names)
    _emit_resources(builder, _mock_resources(rng, equipment))
    _emit_people(builder, _mock_people(rng, fellows, piscine, cohort_names, trial_names))
    if loans:
        _emit_loans(builder, rng, loans)
    return builder.events


def _mock_resources(rng: random.Random, count: int) -> list[dict[str, object]]:
    if count <= 0:
        return []
    existing: list[str] = []
    resources: list[dict[str, object]] = []
    for index in range(count):
        category_name, subcategory_name, stock, needed = MOCK_SLOTS[index % len(MOCK_SLOTS)]
        resource_id = next_sequential_id("R", existing)
        existing.append(resource_id)
        total = max(1, stock + rng.randint(-2, 6))
        resources.append(
            {
                "id": resource_id,
                "name": f"{subcategory_name.replace('-', ' ').title()} {index + 1}",
                "category": category_name,
                "subcategory": subcategory_name,
                "total": total,
                "needed": needed,
            }
        )
    return resources


def _mock_people(
    rng: random.Random,
    fellows: int,
    piscine: int,
    cohort_names: list[str],
    trial_names: list[str],
) -> list[tuple[str, str, str, str]]:
    names = _unique_names(rng, fellows + piscine)
    people: list[tuple[str, str, str, str]] = []
    fellow_ids: list[str] = []
    piscine_ids: list[str] = []

    for index in range(fellows):
        person_id = next_sequential_id("F", fellow_ids)
        fellow_ids.append(person_id)
        cohort = cohort_names[index % len(cohort_names)] if cohort_names else "cluster-1-feb"
        people.append((person_id, names[index], PersonType.FELLOW.value, cohort))

    for offset in range(piscine):
        person_id = next_sequential_id("P", piscine_ids)
        piscine_ids.append(person_id)
        trial = trial_names[offset % len(trial_names)] if trial_names else "trial-period-1"
        people.append((person_id, names[fellows + offset], PersonType.PISCINE.value, trial))
    return people


def _unique_names(rng: random.Random, count: int) -> list[str]:
    pool = [f"{first} {last}" for first in FIRST_NAMES for last in LAST_NAMES]
    rng.shuffle(pool)
    if count <= len(pool):
        return pool[:count]
    names = list(pool)
    suffix = 2
    while len(names) < count:
        for name in pool:
            if len(names) >= count:
                break
            names.append(f"{name} {suffix}")
        suffix += 1
    return names


def _emit_loans(builder: _EventBuilder, rng: random.Random, count: int) -> None:
    resources = [
        (
            str(event.payload["resource"]["id"]),
            int(event.payload["resource"]["available_quantity"]),
        )
        for event in builder.events
        if event.event_type is EventType.RESOURCE_CREATED
    ]
    people = [
        str(event.payload["person"]["id"])
        for event in builder.events
        if event.event_type is EventType.PERSON_CREATED
    ]
    if not resources or not people:
        return

    outstanding: dict[str, int] = {
        resource_id: available for resource_id, available in resources
    }
    transaction_counter = 0
    loan_index = 0

    for _ in range(count):
        resource_id, _ = rng.choice(resources)
        available = outstanding.get(resource_id, 0)
        if available <= 0:
            continue
        quantity = rng.randint(1, min(3, available))
        borrower_id = rng.choice(people)

        transaction_counter += 1
        checkout_id = f"T{transaction_counter:06d}"
        issued_at = builder.tick(seconds=rng.randint(600, 172800))
        due_at = to_iso(
            datetime.fromisoformat(issued_at) + timedelta(days=rng.choice((7, 14, 21)))
        )
        builder.add(
            EventType.LOAN_CHECKED_OUT,
            checkout_payload(
                transaction_id=checkout_id,
                resource_id=resource_id,
                borrower_id=borrower_id,
                quantity=quantity,
                due_at=due_at,
                condition_on_issue=Condition.GOOD,
                issued_by="admin",
                notes="mock checkout",
            ),
            occurred_at=issued_at,
            notes="mock",
        )
        outstanding[resource_id] = available - quantity

        loan_index += 1
        if loan_index % 3 != 0:
            transaction_counter += 1
            returned_at = builder.tick(seconds=rng.randint(3600, 1209600))
            condition = rng.choices(
                (Condition.GOOD, Condition.DAMAGED, Condition.FAULTY),
                weights=(8, 1, 1),
            )[0]
            builder.add(
                EventType.LOAN_RETURNED,
                return_payload(
                    transaction_id=f"T{transaction_counter:06d}",
                    checkout_transaction_id=checkout_id,
                    resource_id=resource_id,
                    borrower_id=borrower_id,
                    quantity=quantity,
                    condition_on_return=condition,
                    returned_by="admin",
                    notes="mock return",
                ),
                occurred_at=returned_at,
                notes="mock",
            )
            outstanding[resource_id] = outstanding.get(resource_id, 0) + quantity
