from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lender.domain.errors import ImportConflict, StorageError, ValidationError
from lender.services.import_export_service import (
    DATASETS,
    EXPORT_FORMAT,
    ImportExportService,
)
from lender.services.inventory_service import InventoryService
from lender.services.lending_service import LendingService
from lender.services.people_service import PeopleService
from lender.services.taxonomy_service import TaxonomyService
from lender.storage.store import Store


def populated(root: Path) -> ImportExportService:
    store = Store.open(root)
    taxonomy = TaxonomyService(store)
    taxonomy.create_category("Electronics")
    taxonomy.create_subcategory("Electronics", "laptop")
    inventory = InventoryService(store, taxonomy)
    people = PeopleService(store)
    lending = LendingService(store)

    people.add_cohort("cluster-1-feb")
    people.add_trial("trial-period-1")
    people.add_fellow("Ada Lovelace", "cluster-1-feb")
    people.add_piscine("Grace Hopper", "trial-period-1")
    inventory.add_resource(
        name="Laptop",
        category="Electronics",
        subcategory="laptop",
        total_quantity=10,
    )
    inventory.add_resource(
        name="Keyboard",
        category="Electronics",
        subcategory="laptop",
        total_quantity=4,
    )
    lending.check_out("R001", "F001", 3)
    lending.return_units("T000001", 1, condition="damaged")
    inventory.mark_condition("R002", "faulty", 2, reason="dead keys")
    return ImportExportService(store)


def snapshot(root: Path) -> dict[str, dict]:
    state = Store.open(root).state
    return {
        name: {
            key: value.to_dict()
            for key, value in getattr(state, name).items()
        }
        for name in ("taxonomy", "groups", "resources", "people", "loans")
    }


class ImportExportTestCase(unittest.TestCase):
    def setUp(self):
        self._source_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._source_tmp.cleanup)
        self.source = Path(self._source_tmp.name)
        self.transfer = populated(self.source)

        self._target_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._target_tmp.cleanup)
        self.target = Path(self._target_tmp.name)

    def target_transfer(self) -> ImportExportService:
        return ImportExportService(Store.open(self.target))


class ExportDocumentTests(ImportExportTestCase):
    def test_json_document_declares_its_format(self):
        document = self.transfer.export_json_document()
        self.assertEqual(document["format"], EXPORT_FORMAT)
        self.assertEqual(document["event_count"], len(document["events"]))

    def test_json_document_carries_every_event(self):
        document = self.transfer.export_json_document()
        self.assertEqual(
            document["event_count"], len(Store.open(self.source).log.read_all())
        )

    def test_csv_headers_match_the_declared_columns(self):
        for dataset in DATASETS:
            with self.subTest(dataset=dataset):
                text = self.transfer.export_csv_text(dataset)
                self.assertEqual(text.splitlines()[0].split(",")[0], "id"
                                 if dataset != "loans" else "transaction_id")

    def test_csv_rows_one_per_record(self):
        state = Store.open(self.source).state
        self.assertEqual(
            len(self.transfer.rows_for("resources")), len(state.resources)
        )
        self.assertEqual(len(self.transfer.rows_for("loans")), len(state.loans))
        self.assertEqual(len(self.transfer.rows_for("people")), len(state.people))

    def test_an_unknown_dataset_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.transfer.rows_for("ghosts")

    def test_a_dataset_is_required_for_csv(self):
        with self.assertRaises(ValidationError):
            self.transfer.write_export(self.target / "x.csv", fmt="csv")

    def test_an_unknown_format_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.transfer.write_export(self.target / "x.txt", fmt="xml")

    def test_json_export_writes_a_readable_file(self):
        path = self.target / "backup.json"
        summary = self.transfer.write_export(path, fmt="json")
        self.assertEqual(summary["events"], self.transfer.export_json_document()["event_count"])
        self.assertTrue(path.is_file())

    def test_csv_export_creates_missing_directories(self):
        path = self.target / "nested" / "resources.csv"
        self.transfer.write_export(path, fmt="csv", dataset="resources")
        self.assertTrue(path.is_file())

    def test_resource_rows_exclude_damage_that_loans_explain(self):
        rows = {row["id"]: row for row in self.transfer.rows_for("resources")}
        self.assertEqual(rows["R001"]["damaged"], 0)
        self.assertEqual(rows["R002"]["faulty"], 2)


class JsonImportTests(ImportExportTestCase):
    def backup(self) -> Path:
        path = self.target / "backup.json"
        self.transfer.write_export(path, fmt="json")
        return path

    def test_replace_loads_a_complete_store(self):
        summary = self.target_transfer().import_file(
            self.backup(), fmt="json", mode="replace"
        )
        self.assertEqual(summary["mode"], "replace")
        self.assertEqual(snapshot(self.target), snapshot(self.source))

    def test_merge_into_an_empty_store_is_the_same_as_replace(self):
        self.target_transfer().import_file(self.backup(), fmt="json")
        self.assertEqual(snapshot(self.target), snapshot(self.source))

    def test_re_importing_the_same_file_adds_nothing(self):
        path = self.backup()
        transfer = self.target_transfer()
        transfer.import_file(path, fmt="json")
        summary = transfer.import_file(path, fmt="json")
        self.assertEqual(summary["imported"], 0)
        self.assertEqual(summary["skipped"], summary["total_events"])
        self.assertEqual(snapshot(self.target), snapshot(self.source))

    def test_replace_discards_whatever_was_there_before(self):
        other = self.target
        transfer = ImportExportService(Store.open(other))
        transfer.import_file(self.backup(), fmt="json")
        TaxonomyService(Store.open(other)).create_category("Scratch")

        transfer.import_file(self.backup(), fmt="json", mode="replace")
        self.assertEqual(snapshot(self.target), snapshot(self.source))

    def test_a_foreign_format_string_is_rejected(self):
        path = self.target / "backup.json"
        path.write_text('{"format": "something-else", "events": []}', encoding="utf-8")
        with self.assertRaises(ValidationError):
            self.target_transfer().import_file(path, fmt="json")

    def test_a_document_without_an_events_array_is_rejected(self):
        path = self.target / "backup.json"
        path.write_text(f'{{"format": "{EXPORT_FORMAT}"}}', encoding="utf-8")
        with self.assertRaises(ValidationError):
            self.target_transfer().import_file(path, fmt="json")

    def test_a_missing_file_is_reported(self):
        with self.assertRaises(StorageError):
            self.target_transfer().import_file(
                self.target / "nowhere.json", fmt="json"
            )

    def test_events_referring_to_missing_records_are_rejected(self):
        document = self.transfer.export_json_document()
        document["events"] = [
            event
            for event in document["events"]
            if event["event_type"] != "resource.created"
            and not event["event_type"].startswith("loan.")
        ]
        with self.assertRaises(ImportConflict):
            self.target_transfer().import_json_document(document, mode="replace")

    def test_a_rejected_import_leaves_the_store_untouched(self):
        transfer = self.target_transfer()
        transfer.import_file(self.backup(), fmt="json")
        before = snapshot(self.target)

        document = transfer.export_json_document()
        document["events"].append(
            {
                "event_id": "E-19700101-0001",
                "event_type": "loan.checked_out",
                "occurred_at": "1970-01-01T00:00:00",
                "actor": "tester",
                "payload": {
                    "transaction_id": "T999999",
                    "resource_id": "nope",
                    "borrower_id": "F001",
                    "quantity": 1,
                    "due_at": "2030-01-01T00:00:00",
                    "condition_on_issue": "good",
                    "issued_by": "tester",
                },
            }
        )
        with self.assertRaises(ImportConflict):
            transfer.import_json_document(document, mode="replace")
        self.assertEqual(snapshot(self.target), before)


class CsvImportTests(ImportExportTestCase):
    def import_all(self, mode="merge") -> None:
        transfer = self.target_transfer()
        for dataset in DATASETS:
            path = self.target / f"{dataset}.csv"
            self.transfer.write_export(path, fmt="csv", dataset=dataset)
            transfer.import_file(path, fmt="csv", dataset=dataset, mode=mode)

    def test_every_dataset_survives_a_round_trip(self):
        self.import_all()
        self.assertEqual(snapshot(self.target), snapshot(self.source))

    def test_loans_carry_the_outstanding_units(self):
        self.import_all()
        target = Store.open(self.target).state
        self.assertEqual(target.resources["R001"].issued_quantity, 2)
        self.assertEqual(target.resources["R001"].available_quantity, 7)

    def test_damage_from_a_return_is_not_double_counted(self):
        self.import_all()
        target = Store.open(self.target).state
        self.assertEqual(target.resources["R001"].condition_counts["damaged"], 1)

    def test_damage_marked_directly_survives(self):
        self.import_all()
        target = Store.open(self.target).state
        self.assertEqual(target.resources["R002"].condition_counts["faulty"], 2)

    def test_a_missing_column_is_reported(self):
        path = self.target / "taxonomy.csv"
        path.write_text("id,name\nC001,Electronics\n", encoding="utf-8")
        with self.assertRaises(ValidationError) as caught:
            self.target_transfer().import_file(
                path, fmt="csv", dataset="taxonomy"
            )
        self.assertIn("missing column", str(caught.exception))

    def test_a_bad_row_is_reported_with_its_line_number(self):
        path = self.target / "resources.csv"
        path.write_text(self.transfer.export_csv_text("resources"), encoding="utf-8")
        broken = path.read_text(encoding="utf-8").replace(
            "R001,Laptop", "R001,Laptop,,,not-a-number"
        )
        path.write_text(broken, encoding="utf-8")
        with self.assertRaises(ValidationError) as caught:
            self.target_transfer().import_file(
                path, fmt="csv", dataset="resources"
            )
        self.assertIn("row 2", str(caught.exception))

    def test_merging_a_record_that_already_exists_is_a_conflict(self):
        path = self.target / "taxonomy.csv"
        self.transfer.write_export(path, fmt="csv", dataset="taxonomy")
        transfer = self.target_transfer()
        transfer.import_file(path, fmt="csv", dataset="taxonomy")
        with self.assertRaises(ImportConflict):
            transfer.import_file(path, fmt="csv", dataset="taxonomy")

    def test_replace_overwrites_the_existing_records(self):
        path = self.target / "taxonomy.csv"
        self.transfer.write_export(path, fmt="csv", dataset="taxonomy")
        transfer = self.target_transfer()
        transfer.import_file(path, fmt="csv", dataset="taxonomy")
        summary = transfer.import_file(
            path, fmt="csv", dataset="taxonomy", mode="replace"
        )
        self.assertEqual(summary["mode"], "replace")
        self.assertEqual(
            snapshot(self.target)["taxonomy"], snapshot(self.source)["taxonomy"]
        )

    def test_a_dataset_is_required_for_csv(self):
        path = self.target / "loans.csv"
        self.transfer.write_export(path, fmt="csv", dataset="loans")
        with self.assertRaises(ValidationError):
            self.target_transfer().import_file(path, fmt="csv")

    def test_loans_without_their_resources_are_rejected(self):
        path = self.target / "loans.csv"
        self.transfer.write_export(path, fmt="csv", dataset="loans")
        with self.assertRaises(ImportConflict):
            self.target_transfer().import_file(path, fmt="csv", dataset="loans")

    def test_created_timestamps_carry_the_causal_order(self):
        self.import_all()
        events = Store.open(self.target).log.read_all()
        created = {
            event.payload["resource"]["id"]: index
            for index, event in enumerate(events)
            if event.event_type.value == "resource.created"
        }
        self.assertTrue(created)
        for index, event in enumerate(events):
            if not event.event_type.value.startswith("loan."):
                continue
            self.assertLess(
                created[event.payload["resource_id"]],
                index,
                "a resource must be created before a loan names it",
            )

    def test_an_unknown_mode_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.target_transfer().import_csv_text(
                self.transfer.export_csv_text("taxonomy"), "taxonomy", mode="squash"
            )


class ReportExportTests(ImportExportTestCase):
    def test_a_json_report_carries_its_payload(self):
        path = self.target / "status.json"
        summary = self.transfer.write_report(
            path, report="store-status", payload={"totals": {"total": 14}}
        )
        document = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(document["format"], EXPORT_FORMAT)
        self.assertEqual(document["report"], "store-status")
        self.assertEqual(document["payload"], {"totals": {"total": 14}})
        self.assertIn("generated_at", document)
        self.assertEqual(summary["format"], "json")

    def test_the_format_is_taken_from_the_file_name(self):
        path = self.target / "status.json"
        self.transfer.write_report(path, report="store-status", payload={})
        self.assertTrue(path.read_text(encoding="utf-8").startswith("{"))

    def test_a_csv_report_writes_its_rows_verbatim(self):
        path = self.target / "rows.csv"
        self.transfer.write_report(
            path,
            report="low-stock",
            payload=[],
            headers=["ID", "Units Out"],
            rows=[["R001", 2]],
        )
        self.assertEqual(path.read_text(encoding="utf-8"), "id,units_out\nR001,2\n")

    def test_a_report_without_a_table_cannot_be_csv(self):
        with self.assertRaises(ValidationError):
            self.transfer.write_report(
                self.target / "rows.csv", report="store-status", payload={"a": 1}
            )

    def test_an_unknown_report_format_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.transfer.write_report(
                self.target / "rows.csv",
                report="store-status",
                payload={},
                fmt="pdf",
            )


if __name__ == "__main__":
    unittest.main()
