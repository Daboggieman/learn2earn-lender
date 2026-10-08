from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lender.domain.events import EventType
from lender.storage.projections import rebuild
from lender.storage.seed_data import (
    SEED_START,
    baseline_events,
    category_id,
    entity_ids,
    mock_events,
    renumber_events,
    subcategory_id,
)
from lender.storage.store import Store


class BaselineSeedTests(unittest.TestCase):
    def setUp(self):
        self.events = baseline_events()

    def test_baseline_has_no_duplicate_event_ids(self):
        identifiers = [event.event_id for event in self.events]
        self.assertEqual(len(identifiers), len(set(identifiers)))

    def test_baseline_replays_into_the_documented_stock(self):
        state = rebuild(self.events)
        self.assertEqual(sorted(state.resources), ["R001", "R002", "R003"])
        self.assertEqual(state.resources["R001"].name, "Laptop")
        self.assertEqual(state.resources["R001"].total_quantity, 10)
        self.assertEqual(state.resources["R002"].total_quantity, 5)
        self.assertEqual(state.resources["R003"].total_quantity, 3)

    def test_baseline_taxonomy_matches_the_seed_table(self):
        state = rebuild(self.events)
        self.assertEqual(len(state.taxonomy), 12)
        self.assertEqual(state.taxonomy["electronics"].name, "Electronics")
        self.assertEqual(
            state.taxonomy["electronics-laptop"].parent_id, "electronics"
        )

    def test_baseline_groups_and_people(self):
        state = rebuild(self.events)
        self.assertEqual(len(state.groups), 11)
        self.assertEqual(sorted(state.people), ["F001", "F002", "F003"])
        self.assertEqual(state.people["F001"].name, "Ada")

    def test_ids_are_slugged_and_parent_prefixed(self):
        self.assertEqual(category_id("Lab Gear"), "lab-gear")
        self.assertEqual(subcategory_id("Lab Gear", "Oscilloscope Probes"), "lab-gear-oscilloscope-probes")

    def test_baseline_starts_at_the_seed_clock(self):
        self.assertEqual(self.events[0].occurred_at, "2026-01-01T08:00:01")

    def test_baseline_invariant_holds_for_every_resource(self):
        state = rebuild(self.events)
        for resource in state.resources.values():
            resource.check_invariant()


class EventHelperTests(unittest.TestCase):
    def test_renumber_events_makes_ids_sequential_per_day(self):
        events = renumber_events(baseline_events())
        seen: dict[str, int] = {}
        for event in events:
            seen[event.date_key] = seen.get(event.date_key, 0) + 1
            stamp = event.date_key.replace("-", "")
            self.assertEqual(event.event_id, f"E-{stamp}-{seen[event.date_key]:04d}")

    def test_entity_ids_collects_every_created_record(self):
        identifiers = entity_ids(baseline_events())
        self.assertIn("R001", identifiers)
        self.assertIn("F001", identifiers)
        self.assertIn("electronics", identifiers)
        self.assertTrue(any(item.startswith("G") for item in identifiers))


def composed_events(start, **overrides):
    options = {
        "fellows": 20,
        "piscine": 5,
        "equipment": 9,
        "cohorts": 3,
        "trials": 4,
        "loans": 30,
        "seed": 77,
    }
    options.update(overrides)
    baseline = baseline_events()
    return renumber_events(
        baseline
        + mock_events(
            start=start,
            emit_taxonomy=False,
            reserved_ids=entity_ids(baseline),
            **options,
        )
    )


class MockSeedTests(unittest.TestCase):
    def build(self, **overrides):
        options = {
            "fellows": 40,
            "piscine": 10,
            "equipment": 18,
            "cohorts": 3,
            "trials": 4,
            "loans": 60,
            "seed": 1234,
        }
        options.update(overrides)
        return mock_events(**options)

    def test_same_seed_produces_identical_events(self):
        first = [event.to_dict() for event in self.build()]
        second = [event.to_dict() for event in self.build()]
        self.assertEqual(first, second)

    def test_different_seeds_produce_different_people(self):
        first = rebuild(self.build(seed=1))
        second = rebuild(self.build(seed=2))
        self.assertNotEqual(
            [person.name for person in first.people.values()],
            [person.name for person in second.people.values()],
        )

    def test_mock_events_replay_without_violating_the_invariant(self):
        state = rebuild(self.build())
        for resource in state.resources.values():
            resource.check_invariant()

    def test_mock_loans_never_over_issue_a_resource(self):
        events = self.build(loans=200)
        state = rebuild(events)
        for resource in state.resources.values():
            self.assertGreaterEqual(resource.available_quantity, 0)
            self.assertGreaterEqual(resource.issued_quantity, 0)
            self.assertLessEqual(resource.issued_quantity, resource.total_quantity)

    def test_returned_units_are_accounted_for_exactly_once(self):
        events = self.build(loans=120)
        state = rebuild(events)
        for loan in state.loans.values():
            self.assertLessEqual(loan.returned_quantity, loan.quantity)

    def test_damaged_returns_leave_circulation(self):
        state = rebuild(self.build(loans=300, seed=99))
        damaged = sum(r.condition_counts["damaged"] for r in state.resources.values())
        faulty = sum(r.condition_counts["faulty"] for r in state.resources.values())
        self.assertGreater(damaged + faulty, 0)

    def test_mock_and_baseline_do_not_collide_on_ids(self):
        combined = composed_events(SEED_START + timedelta(days=1))
        identifiers = [event.event_id for event in combined]
        self.assertEqual(len(identifiers), len(set(identifiers)))

        state = rebuild(combined)
        self.assertEqual(len(state.resources), len(set(state.resources)))
        self.assertEqual(state.resources["R001"].name, "Laptop")
        self.assertEqual(state.resources["R001"].total_quantity, 10)

    def test_mock_following_baseline_needs_reserved_ids_and_a_later_start(self):
        baseline = baseline_events()
        naive = baseline + mock_events(fellows=1, equipment=1, loans=1)
        self.assertNotEqual(
            len([event.event_id for event in naive]),
            len({event.event_id for event in naive}),
        )

    def test_reserved_ids_are_respected(self):
        baseline = baseline_events()
        events = mock_events(
            fellows=5, equipment=5, reserved_ids=entity_ids(baseline)
        )
        state = rebuild(baseline + events)
        self.assertNotIn("R001", [r.id for r in state.resources.values() if r.name != "Laptop"])
        for person_id in ("F001", "F002", "F003"):
            self.assertEqual(
                len([p for p in state.people.values() if p.id == person_id]), 1
            )

    def test_negative_counts_are_rejected(self):
        with self.assertRaises(ValueError):
            mock_events(fellows=-1)

    def test_mock_people_are_split_between_fellows_and_piscine(self):
        state = rebuild(self.build(fellows=12, piscine=4))
        kinds = [person.type.value for person in state.people.values()]
        self.assertEqual(kinds.count("fellow"), 12)
        self.assertEqual(kinds.count("piscine"), 4)

    def test_mock_people_get_unique_names(self):
        state = rebuild(self.build(fellows=300, piscine=90))
        names = [person.name for person in state.people.values()]
        self.assertEqual(len(names), len(set(names)))

    def test_emit_taxonomy_can_be_suppressed(self):
        events = mock_events(fellows=1, emit_taxonomy=False)
        self.assertFalse(
            any(event.event_type is EventType.TAXONOMY_CREATED for event in events)
        )

    def test_mock_loans_reference_mock_borrowers(self):
        events = self.build(fellows=10, piscine=5, loans=40)
        state = rebuild(events)
        borrower_ids = {
            event.payload["borrower_id"]
            for event in events
            if event.event_type is EventType.LOAN_CHECKED_OUT
        }
        self.assertTrue(borrower_ids)
        self.assertTrue(borrower_ids.issubset(set(state.people)))


class SeededStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)

    def test_store_accepts_the_full_seed_batch(self):
        store = Store.open(self.data_dir)
        events = composed_events(SEED_START + timedelta(days=1), fellows=25, loans=40)
        store.extend(events)
        self.assertEqual(len(store.log.read_all()), len(events))

    def test_replaying_the_seeded_store_reproduces_its_state(self):
        store = Store.open(self.data_dir)
        events = composed_events(SEED_START + timedelta(days=1), fellows=15, loans=25)
        store.extend(events)
        replayed = Store.open(self.data_dir).state
        self.assertEqual(
            sorted(replayed.resources), sorted(store.state.resources)
        )
        for resource_id, resource in store.state.resources.items():
            self.assertEqual(replayed.resources[resource_id].to_dict(), resource.to_dict())

    def test_composed_seed_keeps_the_baseline_names(self):
        store = Store.open(self.data_dir)
        store.extend(composed_events(SEED_START + timedelta(days=1)))
        self.assertEqual(store.state.resources["R001"].name, "Laptop")
        self.assertEqual(store.state.resources["R002"].name, "Keyboard")
        self.assertEqual(store.state.people["F001"].name, "Ada")

    def test_seed_clock_is_the_documented_start(self):
        self.assertEqual(SEED_START.isoformat(), "2026-01-01T08:00:00")


if __name__ == "__main__":
    unittest.main()
