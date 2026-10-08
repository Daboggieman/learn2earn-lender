from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lender.domain.equipment import Condition
from lender.domain.errors import StorageError
from lender.domain.events import Event, EventType, format_event_id
from lender.storage import json_repository
from lender.storage.paths import DataPaths
from lender.storage.projections import rebuild
from lender.storage.store import Store
from lender.storage.transaction_log import TransactionLog


class JsonRepositoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_write_then_read_round_trip(self):
        path = self.root / "nested" / "doc.json"
        payload = {"b": [1, 2], "a": {"unicode": "café — 日本語"}}
        json_repository.write_json(path, payload)
        self.assertEqual(json_repository.read_json(path), payload)

    def test_missing_file_returns_default(self):
        self.assertIsNone(json_repository.read_json(self.root / "absent.json"))
        self.assertEqual(
            json_repository.read_json(self.root / "absent.json", default={}), {}
        )

    def test_corrupt_file_raises_storage_error(self):
        path = self.root / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(StorageError):
            json_repository.read_json(path)

    def test_write_leaves_no_temp_files_behind(self):
        path = self.root / "doc.json"
        json_repository.write_json(path, {"ok": True})
        json_repository.write_json(path, {"ok": False})
        self.assertEqual([p.name for p in self.root.iterdir()], ["doc.json"])

    def test_listing_and_delete_ignore_non_json(self):
        json_repository.write_json(self.root / "a.json", {})
        (self.root / "b.txt").write_text("x", encoding="utf-8")
        found = json_repository.list_json_files(self.root)
        self.assertEqual([p.name for p in found], ["a.json"])
        json_repository.delete_file(found[0])
        self.assertEqual(json_repository.list_json_files(self.root), [])

    def test_written_file_is_valid_utf8_json(self):
        path = self.root / "doc.json"
        json_repository.write_json(path, {"name": "Ada"})
        self.assertEqual(
            json.loads(path.read_text(encoding="utf-8")), {"name": "Ada"}
        )


class TransactionLogTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = DataPaths.at(self._tmp.name)
        self.paths.ensure()
        self.log = TransactionLog(self.paths)

    def test_empty_log_reports_empty(self):
        self.assertTrue(self.log.is_empty())
        self.assertEqual(self.log.read_all(), [])
        self.assertEqual(self.log.event_count(), 0)

    def test_append_persists_and_is_readable(self):
        event = self.log.append(
            EventType.TAXONOMY_CREATED,
            {"node": {"id": "electronics", "name": "Electronics"}},
            occurred_at="2026-01-01T08:00:00",
        )
        self.assertEqual(event.event_id, "E-20260101-0001")
        reread = TransactionLog(self.paths).read_all()
        self.assertEqual(len(reread), 1)
        self.assertEqual(reread[0].payload["node"]["id"], "electronics")

    def test_day_file_keeps_date_and_count_metadata(self):
        for index in range(3):
            self.log.append(
                EventType.TAXONOMY_CREATED,
                {"node": {"id": f"n{index}"}},
                occurred_at="2026-01-01T08:00:00",
            )
        document = json_repository.read_json(self.paths.transaction_file("2026-01-01"))
        self.assertEqual(document["date"], "2026-01-01")
        self.assertEqual(document["count"], 3)
        self.assertEqual(len(document["events"]), 3)

    def test_events_spanning_days_split_into_separate_files(self):
        self.log.append(EventType.PERSON_CREATED, {"person": {"id": "F001"}}, occurred_at="2026-01-01T08:00:00")
        self.log.append(EventType.PERSON_CREATED, {"person": {"id": "F002"}}, occurred_at="2026-01-02T08:00:00")
        self.assertEqual(self.log.dates(), ["2026-01-01", "2026-01-02"])
        self.assertEqual(len(self.log.read_day("2026-01-02")), 1)

    def test_sequence_numbers_restart_per_day(self):
        first = self.log.append(EventType.PERSON_CREATED, {"person": {}}, occurred_at="2026-01-01T08:00:00")
        second = self.log.append(EventType.PERSON_CREATED, {"person": {}}, occurred_at="2026-01-02T08:00:00")
        self.assertEqual(first.event_id, "E-20260101-0001")
        self.assertEqual(second.event_id, "E-20260102-0001")

    def test_next_id_resumes_after_reopening(self):
        self.log.append(EventType.PERSON_CREATED, {"person": {}}, occurred_at="2026-01-01T08:00:00")
        reopened = TransactionLog(self.paths)
        self.assertEqual(reopened.next_event_id("2026-01-01T09:00:00"), "E-20260101-0002")

    def test_read_all_sorts_by_time_then_id(self):
        self.log.append(EventType.PERSON_CREATED, {"person": {"id": "late"}}, occurred_at="2026-01-02T08:00:00")
        self.log.append(EventType.PERSON_CREATED, {"person": {"id": "early"}}, occurred_at="2026-01-01T08:00:00")
        order = [event.payload["person"]["id"] for event in self.log.read_all()]
        self.assertEqual(order, ["early", "late"])

    def test_record_many_writes_every_event(self):
        events = [
            Event(
                event_id=format_event_id("2026-01-01", index + 1),
                event_type=EventType.PERSON_CREATED,
                occurred_at="2026-01-01T08:00:00",
                actor="tester",
                payload={"person": {"id": f"F{index:03d}"}},
            )
            for index in range(5)
        ]
        self.log.record_many(events)
        self.assertEqual(self.log.event_count(), 5)

    def test_malformed_day_file_raises_storage_error(self):
        path = self.paths.transaction_file("2026-01-01")
        path.write_text(json.dumps({"date": "2026-01-01"}), encoding="utf-8")
        with self.assertRaises(StorageError):
            self.log.read_all()


class StoreReplayTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)

    def test_reopening_replays_identical_state(self):
        store = Store.open(self.data_dir)
        store.append(EventType.TAXONOMY_CREATED, {"node": {"id": "electronics", "name": "Electronics", "type": "category", "parent_id": None, "status": "active"}})
        store.append(EventType.TAXONOMY_CREATED, {"node": {"id": "electronics-laptop", "name": "laptop", "type": "subcategory", "parent_id": "electronics", "status": "active"}})
        store.append(
            EventType.RESOURCE_CREATED,
            {
                "resource": {
                    "id": "R001",
                    "name": "Laptop",
                    "category_id": "electronics",
                    "subcategory_id": "electronics-laptop",
                    "total_quantity": 10,
                    "available_quantity": 10,
                    "issued_quantity": 0,
                    "status": "active",
                }
            },
        )
        store.append(
            EventType.RESOURCE_CONDITION_CHANGED,
            {"resource_id": "R001", "from": "good", "to": "faulty", "quantity": 3, "reason": ""},
        )
        expected = store.state.resources["R001"].to_dict()

        reopened = Store.open(self.data_dir)
        self.assertEqual(reopened.state.resources["R001"].to_dict(), expected)
        self.assertEqual(reopened.state.events_applied, 4)

    def test_snapshot_matches_replayed_state(self):
        store = Store.open(self.data_dir)
        store.append(EventType.TAXONOMY_CREATED, {"node": {"id": "c", "name": "C", "type": "category", "parent_id": None, "status": "active"}})
        snapshot = json_repository.read_json(store.paths.taxonomy_file)
        self.assertEqual([node["name"] for node in snapshot["nodes"]], ["C"])

    def test_log_replay_matches_incremental_application(self):
        store = Store.open(self.data_dir)
        store.append(EventType.GROUP_CREATED, {"group": {"id": "G001", "name": "cluster-1", "type": "cohort", "status": "active"}})
        for index in range(4):
            store.append(EventType.PERSON_CREATED, {"person": {"id": f"F{index:03d}", "name": f"P{index}", "type": "fellow", "status": "active", "group_id": "G001"}})
        replayed = rebuild(store.log.read_all())
        self.assertEqual(
            {pid: person.name for pid, person in replayed.people.items()},
            {pid: person.name for pid, person in store.state.people.items()},
        )

    def test_empty_store_reports_empty(self):
        self.assertTrue(Store.open(self.data_dir).is_empty())

    def test_refresh_recovers_state_after_failed_append(self):
        store = Store.open(self.data_dir)
        store.append(EventType.GROUP_CREATED, {"group": {"id": "G001", "name": "cluster-1", "type": "cohort", "status": "active"}})
        store.append(EventType.PERSON_CREATED, {"person": {"id": "F001", "name": "Ada", "type": "fellow", "status": "active", "group_id": "G001"}})
        with self.assertRaises(Exception):
            store.append(EventType.PERSON_CREATED, {"person": {"bogus": True}})
        store.refresh()
        self.assertEqual(list(store.state.people), ["F001"])

    def test_condition_change_on_unknown_resource_is_rejected(self):
        store = Store.open(self.data_dir)
        store.append(EventType.GROUP_CREATED, {"group": {"id": "G001", "name": "cluster-1", "type": "cohort", "status": "active"}})
        store.append(
            EventType.PERSON_CREATED,
            {"person": {"id": "F001", "name": "Ada", "type": "fellow", "status": "active", "group_id": "G001"}},
        )
        with self.assertRaises(Exception):
            Store.open(self.data_dir).append(
                EventType.RESOURCE_CONDITION_CHANGED,
                {"resource_id": "R404", "from": "good", "to": "faulty", "quantity": 1},
            )


if __name__ == "__main__":
    unittest.main()
